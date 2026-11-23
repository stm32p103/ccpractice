"""ランナープロトコルのメッセージ(値オブジェクト)。

形と上限は contracts/runner-protocol.schema.json(正本は runner-protocol/schemas/)。標準ライブラリのみ。
未知の項目・上限超過・型の違いは ProtocolViolation として拒否する(additionalProperties: false)。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .vocabulary import (
    MAX_ARTIFACTS,
    MAX_LOG_CHUNK_CHARS,
    MAX_RESULT_SUMMARY_CHARS,
    ArtifactKind,
    FailureReason,
    Outcome,
    Stream,
)


class ProtocolViolation(ValueError):
    """メッセージがスキーマに適合しない。メッセージに入力の値を含めない(項目の名前だけ)。"""

    def __init__(self, field_name: str, reason: str) -> None:
        super().__init__(f"{field_name}: {reason}")
        self.field_name = field_name
        self.reason = reason


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_NAME = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]+$')
_UNC = re.compile(r'^\\\\[^\\/:*?"<>|]+\\[^\\/:*?"<>|]+\\.+')
_HTTPS = re.compile(r"^https://\S+$")
_CREDENTIAL_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _check_keys(data: Mapping[str, Any], allowed: set[str], required: set[str], where: str) -> None:
    if not isinstance(data, Mapping):
        raise ProtocolViolation(where, "オブジェクトでなければならない")
    if set(data) - allowed:
        raise ProtocolViolation(where, "未知の項目がある")
    if required - set(data):
        raise ProtocolViolation(where, "必須の項目がない")


def _int(value: Any, name: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolViolation(name, "整数でなければならない")
    if minimum is not None and value < minimum:
        raise ProtocolViolation(name, "範囲外")
    return value


@dataclass(frozen=True)
class LogChunk:
    seq: int
    stream: Stream
    text: str

    def __post_init__(self) -> None:
        _int(self.seq, "seq", 0)
        if not isinstance(self.stream, Stream):
            raise ProtocolViolation("stream", "stdout または stderr")
        if not isinstance(self.text, str) or len(self.text) > MAX_LOG_CHUNK_CHARS:
            raise ProtocolViolation("text", "上限を超えている")

    def to_json(self) -> dict[str, Any]:
        return {"seq": self.seq, "stream": self.stream.value, "text": self.text}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> LogChunk:
        _check_keys(data, {"seq", "stream", "text"}, {"seq", "stream", "text"}, "LogChunk")
        try:
            stream = Stream(data["stream"])
        except ValueError as exc:
            raise ProtocolViolation("stream", "stdout または stderr") from exc
        return cls(_int(data["seq"], "seq", 0), stream, data["text"])


@dataclass(frozen=True)
class LogChunkResult:
    stored_up_to_seq: int

    def to_json(self) -> dict[str, Any]:
        return {"stored_up_to_seq": self.stored_up_to_seq}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> LogChunkResult:
        _check_keys(data, {"stored_up_to_seq"}, {"stored_up_to_seq"}, "LogChunkResult")
        return cls(_int(data["stored_up_to_seq"], "stored_up_to_seq", -1))


@dataclass(frozen=True)
class SourceCredential:
    """取得資格。secret は repr に出さない。"""

    kind: str
    secret: str = field(repr=False)
    expires_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not _CREDENTIAL_KIND.match(self.kind):
            raise ProtocolViolation("kind", "形式の違反")
        if not isinstance(self.secret, str) or not 1 <= len(self.secret) <= 4096:
            raise ProtocolViolation("secret", "長さの違反")

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "secret": self.secret, "expires_at": self.expires_at}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SourceCredential:
        keys = {"kind", "secret", "expires_at"}
        _check_keys(data, keys, keys, "SourceCredential")
        return cls(data["kind"], data["secret"], data["expires_at"])


@dataclass(frozen=True)
class ArtifactReference:
    name: str
    kind: ArtifactKind
    reference: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 255 or not _ARTIFACT_NAME.match(self.name):
            raise ProtocolViolation("name", "形式の違反")
        if not isinstance(self.kind, ArtifactKind):
            raise ProtocolViolation("kind", "unc または url")
        if not isinstance(self.reference, str) or not 1 <= len(self.reference) <= 1024:
            raise ProtocolViolation("reference", "長さの違反")
        pattern = _UNC if self.kind is ArtifactKind.UNC else _HTTPS
        if not pattern.match(self.reference):
            raise ProtocolViolation("reference", "kind に合う形式でない")
        _int(self.size_bytes, "size_bytes", 0)
        if not isinstance(self.sha256, str) or not _SHA256.match(self.sha256):
            raise ProtocolViolation("sha256", "形式の違反")

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "reference": self.reference,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ArtifactReference:
        keys = {"name", "kind", "reference", "size_bytes", "sha256"}
        _check_keys(data, keys, keys, "ArtifactReference")
        try:
            kind = ArtifactKind(data["kind"])
        except ValueError as exc:
            raise ProtocolViolation("kind", "unc または url") from exc
        return cls(data["name"], kind, data["reference"], _int(data["size_bytes"], "size_bytes", 0), data["sha256"])


@dataclass(frozen=True)
class Counters:
    path_rejections: int = 0
    masked_lines: int = 0
    log_truncated: bool = False

    def __post_init__(self) -> None:
        _int(self.path_rejections, "path_rejections", 0)
        _int(self.masked_lines, "masked_lines", 0)
        if not isinstance(self.log_truncated, bool):
            raise ProtocolViolation("log_truncated", "真偽でなければならない")

    def to_json(self) -> dict[str, Any]:
        return {
            "path_rejections": self.path_rejections,
            "masked_lines": self.masked_lines,
            "log_truncated": self.log_truncated,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Counters:
        keys = {"path_rejections", "masked_lines", "log_truncated"}
        _check_keys(data, keys, keys, "Counters")
        return cls(data["path_rejections"], data["masked_lines"], data["log_truncated"])


@dataclass(frozen=True)
class FinishReport:
    outcome: Outcome
    result_summary: str | None = None
    exit_code: int | None = None
    failure_reason: FailureReason | None = None
    artifacts: tuple[ArtifactReference, ...] = ()
    counters: Counters = field(default_factory=Counters)

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, Outcome):
            raise ProtocolViolation("outcome", "succeeded または failed")
        if self.result_summary is not None and (
            not isinstance(self.result_summary, str) or len(self.result_summary) > MAX_RESULT_SUMMARY_CHARS
        ):
            raise ProtocolViolation("result_summary", "上限を超えている")
        if self.exit_code is not None:
            _int(self.exit_code, "exit_code")
        if self.failure_reason is not None and not isinstance(self.failure_reason, FailureReason):
            raise ProtocolViolation("failure_reason", "固定の語彙でない")
        if self.outcome is Outcome.SUCCEEDED and self.failure_reason is not None:
            raise ProtocolViolation("failure_reason", "成功では指定できない")
        if len(self.artifacts) > MAX_ARTIFACTS:
            raise ProtocolViolation("artifacts", "上限を超えている")

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "result_summary": self.result_summary,
            "exit_code": self.exit_code,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "artifacts": [a.to_json() for a in self.artifacts],
            "counters": self.counters.to_json(),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> FinishReport:
        keys = {"outcome", "result_summary", "exit_code", "failure_reason", "artifacts", "counters"}
        _check_keys(data, keys, {"outcome"}, "FinishReport")
        try:
            outcome = Outcome(data["outcome"])
        except ValueError as exc:
            raise ProtocolViolation("outcome", "succeeded または failed") from exc
        reason = data.get("failure_reason")
        try:
            failure = FailureReason(reason) if reason is not None else None
        except ValueError as exc:
            raise ProtocolViolation("failure_reason", "固定の語彙でない") from exc
        raw_artifacts = data.get("artifacts") or []
        if not isinstance(raw_artifacts, list):
            raise ProtocolViolation("artifacts", "配列でなければならない")
        return cls(
            outcome,
            data.get("result_summary"),
            data.get("exit_code"),
            failure,
            tuple(ArtifactReference.from_json(a) for a in raw_artifacts),
            Counters.from_json(data["counters"]) if "counters" in data else Counters(),
        )


@dataclass(frozen=True)
class HeartbeatResult:
    state: str
    lease_expires_at: str | None
    heartbeat_interval_seconds: float
    abort_requested: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "lease_expires_at": self.lease_expires_at,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "abort_requested": self.abort_requested,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> HeartbeatResult:
        """応答の解釈。将来の互換な追加の項目は無視する(必須の項目は検査する)。"""
        keys = {"state", "lease_expires_at", "heartbeat_interval_seconds", "abort_requested"}
        if not isinstance(data, Mapping) or keys - set(data):
            raise ProtocolViolation("HeartbeatResult", "必須の項目がない")
        interval = data["heartbeat_interval_seconds"]
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
            raise ProtocolViolation("heartbeat_interval_seconds", "正の数でなければならない")
        if not isinstance(data["abort_requested"], bool):
            raise ProtocolViolation("abort_requested", "真偽でなければならない")
        return cls(data["state"], data["lease_expires_at"], float(interval), data["abort_requested"])


@dataclass(frozen=True)
class StoredLogChunk:
    seq: int
    stream: Stream
    text: str
    received_at: str


@dataclass(frozen=True)
class LogPage:
    chunks: tuple[StoredLogChunk, ...]
    next_seq: int
    complete: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "chunks": [
                {"seq": c.seq, "stream": c.stream.value, "text": c.text, "received_at": c.received_at}
                for c in self.chunks
            ],
            "next_seq": self.next_seq,
            "complete": self.complete,
        }
