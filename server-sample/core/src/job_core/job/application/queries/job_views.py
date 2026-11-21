"""表示用の型(contracts/application-api.md「ListJobs」「GetJob」)。

一覧(JobSummaryView)は payload を含まない。詳細(JobDetailView)は定義(payload を含む)を持つ。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from job_core.job.domain.job import Job
from job_core.job.domain.states import JobState
from job_core.job.domain.values import JsonValue
from job_core.shared.ids import JobId, SubjectId


@dataclass(frozen=True)
class JobSummaryView:
    job_id: JobId
    job_type: str
    owner: SubjectId
    submitted_by: SubjectId
    state: JobState
    position: int | None
    submitted_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_summary: str | None
    abort_pending: bool
    retry_of: JobId | None

    @classmethod
    def of(cls, job: Job, position: int | None) -> JobSummaryView:
        return cls(
            job_id=job.job_id,
            job_type=job.definition.job_type.value,
            owner=job.submitter.owner,
            submitted_by=job.submitter.submitted_by,
            state=job.state,
            position=position,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            result_summary=job.result_summary.value if job.result_summary else None,
            abort_pending=job.abort_pending,
            retry_of=job.retry_of,
        )


@dataclass(frozen=True)
class DefinitionView:
    job_type: str
    requirement: JsonValue
    payload: JsonValue
    timeout: timedelta
    source: str | None
    revision: str | None


@dataclass(frozen=True)
class CancellationView:
    kind: str
    requested_by: SubjectId
    requested_at: datetime
    reason: str | None
    confirmed_at: datetime | None
    superseded_by: JobState | None


@dataclass(frozen=True)
class RelatedJobRef:
    """関連するジョブへの参照。保持期間を過ぎて削除されていれば exists = False。"""

    job_id: JobId
    exists: bool


@dataclass(frozen=True)
class JobDetailView:
    summary: JobSummaryView
    definition: DefinitionView
    cancellation: CancellationView | None
    retry_of: RelatedJobRef | None
    retries: tuple[JobId, ...]


@dataclass(frozen=True)
class JobListView:
    queued: tuple[JobSummaryView, ...]
    """待機中の全件。待機列の並び順。"""
    running: tuple[JobSummaryView, ...]
    finished: tuple[JobSummaryView, ...]
    """終了済み。finished_at の新しい順で頁送り。"""
    next_cursor: str | None


def definition_view(job: Job) -> DefinitionView:
    source_ref = job.definition.source_ref
    return DefinitionView(
        job_type=job.definition.job_type.value,
        requirement=job.definition.requirement.value,
        payload=job.definition.payload.value,
        timeout=job.definition.timeout.value,
        source=source_ref.source if source_ref else None,
        revision=source_ref.revision if source_ref else None,
    )


def cancellation_view(job: Job) -> CancellationView | None:
    record = job.cancellation
    if record is None:
        return None
    return CancellationView(
        kind=record.kind.value,
        requested_by=record.requested_by,
        requested_at=record.requested_at,
        reason=record.reason.value if record.reason else None,
        confirmed_at=record.confirmed_at,
        superseded_by=record.superseded_by,
    )
