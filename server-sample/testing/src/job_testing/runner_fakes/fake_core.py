"""偽のコア(ランナープロトコルを話す、メモリ上の HTTP の模擬。004 T020。FR-012)。

`httpx.MockTransport` として CoreClient に渡す。ジョブの投入、リースの動作(切れ)、中断の要求、受信した全要求の記録、
途絶・拒否の注入を持つ。本物のコア API(003)と同じ JSON の形を返す(`RunnerProtocolContract` で一致を検査する)。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from job_runner_protocol.messages import FinishReport, LogChunk, ProtocolViolation

TOKEN = "rt_fake0123456789abcdef0123456789"


@dataclass
class RecordedRequest:
    method: str
    path: str
    body: Any
    authorized: bool


@dataclass
class FakeJob:
    job_id: str
    job_type: str
    payload: Any
    timeout_seconds: float
    source: str | None
    revision: str | None
    state: str = "queued"
    lease_id: str | None = None
    lease_expires_at: float | None = None
    abort_requested: bool = False
    report: FinishReport | None = None
    failure_reason: str | None = None
    logs: dict[int, tuple[str, str]] = field(default_factory=dict)


class FakeRunnerCore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        lease_seconds: float = 180.0,
        heartbeat_interval: float = 30.0,
        log_quota_chars: int = 10 * 1024 * 1024,
    ) -> None:
        self.clock = clock
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self.log_quota_chars = log_quota_chars
        self.token = TOKEN
        self.jobs: dict[str, FakeJob] = {}
        self.queue: list[str] = []
        self.requests: list[RecordedRequest] = []
        self.registrations: list[dict[str, Any]] = []
        self.faults: list[str | None] = []
        self.credentials_issued = 0
        self.source_credentials_enabled = True
        self.down = False
        """真の間、接続できない(途絶の注入)。"""
        self.fail_next: list[int] = []
        """次の要求に返す 5xx などの状態コード(先頭から消費する)。"""
        self.drop_log_responses = 0
        """この回数だけ、ログの追加を保存した上で応答を落とす(再送の検査)。"""
        self.transport = httpx.MockTransport(self.handle)
        self._next = 0

    # ------------------------------------------------------------------ 試験からの操作

    def enqueue(
        self,
        job_type: str = "type-a",
        payload: Any = None,
        timeout_seconds: float = 60.0,
        source: str | None = None,
        revision: str | None = None,
    ) -> str:
        self._next += 1
        job_id = f"job-{self._next}"
        self.jobs[job_id] = FakeJob(job_id, job_type, payload or {}, timeout_seconds, source, revision)
        self.queue.append(job_id)
        return job_id

    def request_abort(self, job_id: str) -> None:
        self.jobs[job_id].abort_requested = True

    def log_text(self, job_id: str) -> str:
        logs = self.jobs[job_id].logs
        return "".join(logs[seq][1] for seq in sorted(logs))

    def settle(self) -> None:
        """時刻の経過によるリース切れを反映する。"""
        now = self.clock()
        for job in self.jobs.values():
            if job.state == "running" and job.lease_expires_at is not None and now > job.lease_expires_at:
                job.state = "failed"
                job.failure_reason = "lease_expired"

    def recorded_text(self) -> str:
        """受信した全要求の本文を 1 つの文字列にしたもの(秘密の混入の検査用)。"""
        return json.dumps([r.body for r in self.requests], ensure_ascii=False, default=str)

    # ------------------------------------------------------------------ HTTP

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("fake core is down", request=request)
        body: Any = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = None
        authorized = request.headers.get("authorization") == f"Bearer {self.token}"
        self.requests.append(RecordedRequest(request.method, request.url.path, body, authorized))
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"code": "internal_error"})
        if not authorized:
            return self._error(401, "authentication_failed")
        self.settle()
        return self._route(request.method, request.url.path, body)

    def _route(self, method: str, path: str, body: Any) -> httpx.Response:
        if path == "/v1/runner/registration" and method == "POST":
            self.registrations.append(dict((body or {}).get("capabilities", {})))
            return self._heartbeat_response()
        if path == "/v1/runner/heartbeat" and method == "POST":
            return self._heartbeat_response(extend=True)
        if path == "/v1/runner/fault":
            if method == "POST":
                description = (body or {}).get("description")
                if not isinstance(description, str) or not 1 <= len(description) <= 200:
                    return self._error(422, "validation_failed")
                self.faults.append(description)
            else:
                self.faults.append(None)
            return self._heartbeat_response()
        if path == "/v1/runner/job-requests" and method == "POST":
            return self._job_request()
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:3] == ["v1", "runner", "jobs"]:
            job = self.jobs.get(parts[3])
            if job is None:
                return self._error(404, "job_not_found")
            action = parts[4]
            if action == "logs":
                return self._logs(job, body)
            if action == "result":
                return self._result(job, body)
            if action == "stopped":
                return self._stopped(job)
            if action == "source-credential":
                return self._source_credential(job)
        return self._error(404, "not_found")

    def _heartbeat_response(self, *, extend: bool = False) -> httpx.Response:
        running = next((j for j in self.jobs.values() if j.state == "running"), None)
        expires: float | None = None
        abort = False
        if running is not None and running.lease_expires_at is not None:
            if extend:
                running.lease_expires_at = self.clock() + self.lease_seconds
            expires = running.lease_expires_at
            abort = running.abort_requested
        return httpx.Response(
            200,
            json={
                "state": "online",
                "lease_expires_at": self._iso(expires) if expires is not None else None,
                "heartbeat_interval_seconds": self.heartbeat_interval,
                "abort_requested": abort,
            },
        )

    def _job_request(self) -> httpx.Response:
        running = next((j for j in self.jobs.values() if j.state == "running"), None)
        interval = self.heartbeat_interval
        if running is not None:
            reason = {"kind": "runner_busy", "state": None, "job_id": running.job_id}
            return httpx.Response(
                200, json={"assignment": None, "not_assigned_reason": reason, "heartbeat_interval_seconds": interval}
            )
        while self.queue:
            job = self.jobs[self.queue.pop(0)]
            if job.state != "queued":
                continue
            job.state = "running"
            job.lease_id = f"lease-{job.job_id}"
            job.lease_expires_at = self.clock() + self.lease_seconds
            assignment = {
                "job_id": job.job_id,
                "definition": {
                    "job_type": job.job_type,
                    "requirement": {"all": []},
                    "payload": job.payload,
                    "timeout_seconds": job.timeout_seconds,
                    "source": job.source,
                    "revision": job.revision,
                },
                "lease_id": job.lease_id,
                "lease_expires_at": self._iso(job.lease_expires_at),
            }
            return httpx.Response(
                200,
                json={"assignment": assignment, "not_assigned_reason": None, "heartbeat_interval_seconds": interval},
            )
        reason = {"kind": "no_matching_job", "state": None, "job_id": None}
        return httpx.Response(
            200, json={"assignment": None, "not_assigned_reason": reason, "heartbeat_interval_seconds": interval}
        )

    def _logs(self, job: FakeJob, body: Any) -> httpx.Response:
        if job.state != "running":
            return self._error(409, "target_not_running")
        try:
            chunk = LogChunk.from_json(body)
        except (ProtocolViolation, TypeError):
            return self._error(422, "validation_failed")
        existing = job.logs.get(chunk.seq)
        if existing is not None and existing != (chunk.stream.value, chunk.text):
            return self._error(409, "log_seq_conflict")
        if existing is None:
            total = sum(len(text) for _, text in job.logs.values())
            if total + len(chunk.text) > self.log_quota_chars:
                return self._error(409, "log_quota_exceeded")
            job.logs[chunk.seq] = (chunk.stream.value, chunk.text)
        seq = -1
        while seq + 1 in job.logs:
            seq += 1
        if self.drop_log_responses > 0:
            self.drop_log_responses -= 1
            return httpx.Response(503, json={"code": "internal_error"})
        return httpx.Response(200, json={"stored_up_to_seq": seq})

    def _result(self, job: FakeJob, body: Any) -> httpx.Response:
        if job.state != "running":
            code = "lease_expired" if job.failure_reason == "lease_expired" else "invalid_state_transition"
            return self._error(409, code)
        try:
            report = FinishReport.from_json(body)
        except (ProtocolViolation, TypeError):
            return self._error(422, "validation_failed")
        job.state = report.outcome.value
        job.report = report
        job.failure_reason = report.failure_reason.value if report.failure_reason else None
        return httpx.Response(200, json={"job_id": job.job_id, "state": job.state, "superseded_abort": False})

    def _stopped(self, job: FakeJob) -> httpx.Response:
        if job.state != "running" or not job.abort_requested:
            return self._error(409, "invalid_state_transition")
        job.state = "cancelled"
        return httpx.Response(200, json={"job_id": job.job_id, "state": "cancelled", "superseded_abort": False})

    def _source_credential(self, job: FakeJob) -> httpx.Response:
        if job.state != "running":
            return self._error(409, "target_not_running")
        if not self.source_credentials_enabled:
            return self._error(422, "source_not_available")
        self.credentials_issued += 1
        return httpx.Response(
            200,
            json={
                "kind": "token",
                "secret": f"srcsecret-{self.credentials_issued:04d}-0123456789abcdef",
                "expires_at": self._iso(self.clock() + 600),
            },
        )

    # ------------------------------------------------------------------ 補助

    @staticmethod
    def _error(status: int, code: str) -> httpx.Response:
        return httpx.Response(status, json={"code": code, "title": code, "status": status})

    @staticmethod
    def _iso(monotonic_seconds: float) -> str:
        base = datetime(2026, 11, 22, tzinfo=UTC)
        return (base + timedelta(seconds=monotonic_seconds)).isoformat().replace("+00:00", "Z")
