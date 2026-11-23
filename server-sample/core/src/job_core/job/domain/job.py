"""Job 集約(data-model.md §2)。

項目: Job.job_id、.definition、.submitter、.submitted_at、.state、.assigned_runner_id、.started_at、
.finished_at、.result_summary、.cancellation、.retry_of、.version。
状態の変更はメソッドだけで行い、規則にない遷移は InvalidStateTransition(FR-021)。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from job_core.shared.ids import JobId, RunnerId, SubjectId, is_valid_id

from .definition import JobDefinition, Submitter
from .errors import AbortAlreadyRequested, InvalidStateTransition, ReasonRequired, RunnerMismatch
from .events import JobCompleted
from .output import ResultDetail
from .states import JobState
from .values import Reason, ResultSummary


class CancellationKind(StrEnum):
    QUEUED_CANCEL = "queued_cancel"
    FORCE_ABORT = "force_abort"


@dataclass(frozen=True)
class CancellationRecord:
    """中断の記録(data-model.md CancellationRecord.kind、.requested_by、.requested_at、.reason、
    .confirmed_at、.superseded_by)。"""

    kind: CancellationKind
    requested_by: SubjectId
    requested_at: datetime
    reason: Reason | None
    confirmed_at: datetime | None = None
    superseded_by: JobState | None = None

    def __post_init__(self) -> None:
        if self.kind is CancellationKind.FORCE_ABORT and self.reason is None:
            raise ReasonRequired()
        if self.superseded_by is not None and self.superseded_by not in (JobState.SUCCEEDED, JobState.FAILED):
            raise ValueError("superseded_by は SUCCEEDED または FAILED")


@dataclass(eq=False)
class Job:
    job_id: JobId
    definition: JobDefinition
    submitter: Submitter
    submitted_at: datetime
    state: JobState = JobState.QUEUED
    assigned_runner_id: RunnerId | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_summary: ResultSummary | None = None
    result_detail: ResultDetail | None = None
    cancellation: CancellationRecord | None = None
    retry_of: JobId | None = None
    version: int = 0
    _events: list[JobCompleted] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ 生成

    @classmethod
    def submit(
        cls,
        *,
        job_id: JobId,
        definition: JobDefinition,
        submitter: Submitter,
        at: datetime,
        retry_of: JobId | None = None,
    ) -> Job:
        if not is_valid_id(job_id):
            raise ValueError("job_id は空でない文字列でなければならない")
        return cls(job_id=job_id, definition=definition, submitter=submitter, submitted_at=at, retry_of=retry_of)

    # ------------------------------------------------------------------ 参照

    @property
    def abort_pending(self) -> bool:
        """強制中断を要求済みで、まだ確定していない。"""
        return (
            self.state is JobState.RUNNING
            and self.cancellation is not None
            and self.cancellation.kind is CancellationKind.FORCE_ABORT
            and self.cancellation.confirmed_at is None
        )

    def pull_events(self) -> list[JobCompleted]:
        """積まれたドメインイベントを取り出す(取り出した分は消える)。"""
        events, self._events = self._events, []
        return events

    # ------------------------------------------------------------------ 遷移

    def assign(self, runner_id: RunnerId, at: datetime) -> None:
        self._require_state(JobState.QUEUED, "assign")
        if not is_valid_id(runner_id):
            raise ValueError("runner_id は空でない文字列でなければならない")
        self.state = JobState.RUNNING
        self.assigned_runner_id = runner_id
        self.started_at = at

    def cancel_queued(self, *, by: SubjectId, reason: Reason | None, at: datetime, event_id: str) -> None:
        self._require_state(JobState.QUEUED, "cancel_queued")
        self.cancellation = CancellationRecord(
            kind=CancellationKind.QUEUED_CANCEL, requested_by=by, requested_at=at, reason=reason, confirmed_at=at
        )
        self._finish_with(JobState.CANCELLED, at, event_id)

    def request_abort(self, *, by: SubjectId, reason: Reason | None, at: datetime) -> None:
        self._require_state(JobState.RUNNING, "request_abort")
        if self.cancellation is not None:
            raise AbortAlreadyRequested(self.cancellation.requested_at)
        if reason is None:
            raise ReasonRequired()
        self.cancellation = CancellationRecord(
            kind=CancellationKind.FORCE_ABORT, requested_by=by, requested_at=at, reason=reason
        )

    def confirm_stopped(self, *, runner_id: RunnerId, at: datetime, event_id: str) -> None:
        self._require_reporting_runner(runner_id, "confirm_stopped")
        if not self.abort_pending or self.cancellation is None:
            raise InvalidStateTransition(self.state.value, "confirm_stopped")
        self.cancellation = replace(self.cancellation, confirmed_at=at)
        self._finish_with(JobState.CANCELLED, at, event_id)

    def finish(
        self,
        *,
        runner_id: RunnerId,
        outcome: JobState,
        summary: ResultSummary | None,
        at: datetime,
        event_id: str,
        detail: ResultDetail | None = None,
    ) -> None:
        self._require_reporting_runner(runner_id, "finish")
        if outcome not in (JobState.SUCCEEDED, JobState.FAILED):
            raise ValueError("outcome は SUCCEEDED または FAILED")
        if self.abort_pending and self.cancellation is not None:
            # 停止の確認より先に終了が確定した。終了を正とし、中断の要求はその旨とともに残す。
            self.cancellation = replace(self.cancellation, superseded_by=outcome)
        self.result_summary = summary
        self.result_detail = detail
        self._finish_with(outcome, at, event_id)

    # ------------------------------------------------------------------ 内部

    def _require_state(self, expected: JobState, operation: str) -> None:
        if self.state is not expected:
            raise InvalidStateTransition(self.state.value, operation)

    def _require_reporting_runner(self, runner_id: RunnerId, operation: str) -> None:
        # 待機中は割り当て先がないため、状態の誤りとして扱う。それ以外は割り当て先の一致を状態より先に検査する。
        if self.state is JobState.QUEUED:
            raise InvalidStateTransition(self.state.value, operation)
        if runner_id != self.assigned_runner_id:
            raise RunnerMismatch(self.job_id)
        if self.state is not JobState.RUNNING:
            raise InvalidStateTransition(self.state.value, operation)

    def _finish_with(self, state: JobState, at: datetime, event_id: str) -> None:
        self.state = state
        self.finished_at = at
        self._events.append(
            JobCompleted(
                event_id=event_id,
                occurred_at=at,
                job_id=self.job_id,
                state=state,
                finished_at=at,
                retry_of=self.retry_of,
                submitter_id=self.submitter.owner,
            )
        )
