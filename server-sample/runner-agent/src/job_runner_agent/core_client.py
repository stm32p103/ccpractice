"""ランナープロトコルのクライアント(contracts/runner-protocol.md。research.md R13)。

1 回の呼び出しは 1 回の試行。失敗は 2 種類に分ける。
- CoreUnavailable: 接続の失敗・タイムアウト・5xx・429。再試行してよい(バックオフは retry.py)。
- CoreRejected: コアが明確に拒否した(4xx)。status と problem の code を持つ。確定の拒否(final)かどうかを判定できる。
トークン・取得資格を、例外・repr・ログに出さない。送る本文は送信前にスキーマで検査する。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from job_runner_protocol.messages import (
    FinishReport,
    HeartbeatResult,
    LogChunk,
    LogChunkResult,
    ProtocolViolation,
    SourceCredential,
)

from .secret_source import SecretValue

# 確定の拒否: 再試行しても結果が変わらない(結果の重複を防ぐため、記録して破棄する)
FINAL_REJECTION_CODES = frozenset(
    {"invalid_state_transition", "lease_expired", "target_not_running", "runner_mismatch", "job_not_found"}
)


class CoreUnavailable(Exception):
    """到達できない・一時的な失敗。メッセージに本文・秘密を含めない。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CoreRejected(Exception):
    """コアの拒否(4xx)。"""

    def __init__(self, status: int, code: str | None) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code

    @property
    def final(self) -> bool:
        """再試行しても変わらない拒否。"""
        return self.status in (403, 404) or self.code in FINAL_REJECTION_CODES


@dataclass(frozen=True)
class Assignment:
    job_id: str
    job_type: str
    payload: Any
    timeout_seconds: float
    source: str | None
    revision: str | None
    lease_id: str
    lease_expires_at: str


@dataclass(frozen=True)
class JobRequestResult:
    assignment: Assignment | None
    heartbeat_interval_seconds: float


class CoreClient:
    def __init__(
        self,
        base_url: str,
        token: SecretValue,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        verify: bool | str = True,
        allow_insecure: bool = False,
        timeout: float = 15.0,
    ) -> None:
        if base_url.startswith("http://") and not allow_insecure:
            raise ValueError("prod では HTTPS のみ")
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            verify=verify,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,  # 環境のプロキシ設定を使わない(送信先を設定の 1 か所に限る)
        )

    def __repr__(self) -> str:
        return "CoreClient(***)"

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ 003 の最小版

    async def register(self, capabilities: Mapping[str, Any]) -> HeartbeatResult:
        return HeartbeatResult.from_json(
            await self._call("POST", "/v1/runner/registration", {"capabilities": dict(capabilities)})
        )

    async def heartbeat(self) -> HeartbeatResult:
        return self._heartbeat(await self._call("POST", "/v1/runner/heartbeat"))

    async def report_fault(self, description: str) -> HeartbeatResult:
        return self._heartbeat(await self._call("POST", "/v1/runner/fault", {"description": description}))

    async def report_recovered(self) -> HeartbeatResult:
        return self._heartbeat(await self._call("DELETE", "/v1/runner/fault"))

    async def request_job(self) -> JobRequestResult:
        data = await self._call("POST", "/v1/runner/job-requests")
        try:
            interval = float(data["heartbeat_interval_seconds"])
            raw = data.get("assignment")
            assignment = None
            if raw is not None:
                definition = raw["definition"]
                assignment = Assignment(
                    job_id=str(raw["job_id"]),
                    job_type=str(definition["job_type"]),
                    payload=definition.get("payload"),
                    timeout_seconds=float(definition["timeout_seconds"]),
                    source=definition.get("source"),
                    revision=definition.get("revision"),
                    lease_id=str(raw["lease_id"]),
                    lease_expires_at=str(raw["lease_expires_at"]),
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise CoreUnavailable("応答の形式が不正") from exc
        return JobRequestResult(assignment, interval)

    async def report_result(self, job_id: str, report: FinishReport) -> dict[str, Any]:
        return await self._call("POST", f"/v1/runner/jobs/{job_id}/result", report.to_json())

    async def confirm_stopped(self, job_id: str) -> dict[str, Any]:
        return await self._call("POST", f"/v1/runner/jobs/{job_id}/stopped")

    # ------------------------------------------------------------------ 004 の追加

    async def append_log(self, job_id: str, chunk: LogChunk) -> LogChunkResult:
        return self._log_result(await self._call("POST", f"/v1/runner/jobs/{job_id}/logs", chunk.to_json()))

    async def source_credential(self, job_id: str) -> SourceCredential:
        data = await self._call("POST", f"/v1/runner/jobs/{job_id}/source-credential", {})
        try:
            return SourceCredential.from_json(data)
        except ProtocolViolation as exc:
            raise CoreUnavailable("応答の形式が不正") from exc

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _heartbeat(data: dict[str, Any]) -> HeartbeatResult:
        try:
            return HeartbeatResult.from_json(data)
        except ProtocolViolation as exc:
            raise CoreUnavailable("応答の形式が不正") from exc

    @staticmethod
    def _log_result(data: dict[str, Any]) -> LogChunkResult:
        try:
            return LogChunkResult.from_json(data)
        except ProtocolViolation as exc:
            raise CoreUnavailable("応答の形式が不正") from exc

    async def _call(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token.reveal()}", "Accept": "application/json"}
        try:
            if body is None:
                response = await self._client.request(method, path, headers=headers)
            else:
                response = await self._client.request(method, path, headers=headers, json=dict(body))
        except httpx.HTTPError as exc:
            raise CoreUnavailable(type(exc).__name__) from None  # 例外の文字列(URL・本文を含みうる)を出さない
        if response.status_code >= 500 or response.status_code == 429:
            raise CoreUnavailable(f"status {response.status_code}")
        if response.status_code >= 400:
            code: str | None = None
            try:
                value = response.json().get("code")
                code = value if isinstance(value, str) else None
            except (ValueError, AttributeError):
                pass
            raise CoreRejected(response.status_code, code)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise CoreUnavailable("応答の形式が不正") from exc
        if not isinstance(data, dict):
            raise CoreUnavailable("応答の形式が不正")
        return data
