"""ランナー向けのモデル(contracts/http-api.md §2.6。research.md R16)。

割り当ての応答だけが、ジョブ定義(payload を含む)を持つ(台帳 E16)。ランナーの識別子は URL にも本文にも含めない。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from job_core.job.application import FinishResult, LogPageView
from job_core.job.domain.output import JobArtifactRef
from job_core.job.domain.states import JobState
from job_core.runner.application.results import (
    Assignment,
    HeartbeatResult,
    JobRequestResult,
    NotAssignedKind,
    NotAssignedReason,
)
from job_core.runner.domain.runner import RunnerState

from .schemas_jobs import ApiModel, DefinitionOut


class RegisterRequest(ApiModel):
    capabilities: dict[str, Any] = Field(
        description="能力の申告(キー → 文字列または文字列の配列)。許可リストのキーに限る"
    )


class FaultRequest(ApiModel):
    description: str = Field(description="異常の短い説明(1〜200 文字)")


class ArtifactReferenceIn(ApiModel):
    """成果物の参照(004)。中身を持たない。UNC パスまたは HTTPS の URL。"""

    name: str = Field(min_length=1, max_length=255)
    kind: Literal["unc", "url"]
    reference: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class ArtifactReferenceOut(ApiModel):
    name: str
    kind: Literal["unc", "url"]
    reference: str
    size_bytes: int
    sha256: str

    @classmethod
    def of(cls, ref: JobArtifactRef) -> ArtifactReferenceOut:
        return cls(
            name=ref.name, kind=ref.kind.value, reference=ref.reference, size_bytes=ref.size_bytes, sha256=ref.sha256
        )


class CountersIn(ApiModel):
    path_rejections: int = Field(ge=0)
    masked_lines: int = Field(ge=0)
    log_truncated: bool


class FinishRequest(ApiModel):
    outcome: Literal["succeeded", "failed"]
    result_summary: str | None = Field(default=None, max_length=200)
    exit_code: int | None = None
    failure_reason: str | None = None
    artifacts: list[ArtifactReferenceIn] = Field(default_factory=list, max_length=100)
    counters: CountersIn | None = None


class LogChunkIn(ApiModel):
    seq: int = Field(ge=0)
    stream: Literal["stdout", "stderr"]
    text: str = Field(max_length=65536)


class LogChunkResultOut(ApiModel):
    stored_up_to_seq: int


class LogChunkOut(ApiModel):
    seq: int
    stream: Literal["stdout", "stderr"]
    text: str
    received_at: datetime


class LogPageOut(ApiModel):
    chunks: list[LogChunkOut]
    next_seq: int
    complete: bool

    @classmethod
    def of(cls, view: LogPageView) -> LogPageOut:
        return cls(
            chunks=[
                LogChunkOut(seq=c.seq, stream=c.stream.value, text=c.text, received_at=c.received_at)
                for c in view.chunks
            ],
            next_seq=view.next_seq,
            complete=view.complete,
        )


class SourceCredentialOut(ApiModel):
    kind: str
    secret: str
    expires_at: datetime


class ArtifactListOut(ApiModel):
    artifacts: list[ArtifactReferenceOut]


class HeartbeatResultOut(ApiModel):
    state: RunnerState
    lease_expires_at: datetime | None
    heartbeat_interval_seconds: float
    abort_requested: bool = False
    """004: 割り当て中のジョブに中断の要求がある(強制中断の指示)。"""

    @classmethod
    def of(cls, result: HeartbeatResult) -> HeartbeatResultOut:
        return cls(
            state=result.state,
            lease_expires_at=result.lease_expires_at,
            heartbeat_interval_seconds=result.heartbeat_interval.total_seconds(),
            abort_requested=result.abort_requested,
        )


class AssignmentOut(ApiModel):
    job_id: str
    definition: DefinitionOut
    lease_id: str
    lease_expires_at: datetime

    @classmethod
    def of(cls, assignment: Assignment) -> AssignmentOut:
        return cls(
            job_id=assignment.job_id,
            definition=DefinitionOut.of(assignment.definition),
            lease_id=assignment.lease_id,
            lease_expires_at=assignment.lease_expires_at,
        )


class NotAssignedReasonOut(ApiModel):
    kind: NotAssignedKind
    state: RunnerState | None
    job_id: str | None

    @classmethod
    def of(cls, reason: NotAssignedReason) -> NotAssignedReasonOut:
        return cls(kind=reason.kind, state=reason.state, job_id=reason.job_id)


class JobRequestResultOut(ApiModel):
    assignment: AssignmentOut | None
    not_assigned_reason: NotAssignedReasonOut | None
    heartbeat_interval_seconds: float

    @classmethod
    def of(cls, result: JobRequestResult) -> JobRequestResultOut:
        return cls(
            assignment=AssignmentOut.of(result.assignment) if result.assignment else None,
            not_assigned_reason=NotAssignedReasonOut.of(result.not_assigned_reason)
            if result.not_assigned_reason
            else None,
            heartbeat_interval_seconds=result.heartbeat_interval.total_seconds(),
        )


class FinishResultOut(ApiModel):
    job_id: str
    state: JobState
    superseded_abort: bool

    @classmethod
    def of(cls, result: FinishResult) -> FinishResultOut:
        return cls(job_id=result.job_id, state=result.state, superseded_abort=result.superseded_abort)
