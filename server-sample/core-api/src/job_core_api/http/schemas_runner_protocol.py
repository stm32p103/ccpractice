"""ランナー向けのモデル(contracts/http-api.md §2.6。research.md R16)。

割り当ての応答だけが、ジョブ定義(payload を含む)を持つ(台帳 E16)。ランナーの識別子は URL にも本文にも含めない。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from job_core.job.application import FinishResult
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


class FinishRequest(ApiModel):
    outcome: Literal["succeeded", "failed"]
    result_summary: str | None = None


class HeartbeatResultOut(ApiModel):
    state: RunnerState
    lease_expires_at: datetime | None
    heartbeat_interval_seconds: float

    @classmethod
    def of(cls, result: HeartbeatResult) -> HeartbeatResultOut:
        return cls(
            state=result.state,
            lease_expires_at=result.lease_expires_at,
            heartbeat_interval_seconds=result.heartbeat_interval.total_seconds(),
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
