"""ジョブ完了イベント(data-model.md §5 JobCompleted)。

項目は JobCompleted.event_id、.event_type、.schema_version、.occurred_at、.job_id、.state、.finished_at、
.retry_of、.submitter_id に限る。payload・ログ本文・結果の要約・ランナーの情報を持たない(FR-030)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from job_core.shared.events import DomainEvent
from job_core.shared.ids import JobId, SubjectId

from .states import JobState

EVENT_TYPE_JOB_COMPLETED = "job.completed"
JOB_COMPLETED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class JobCompleted(DomainEvent):
    event_type: ClassVar[str] = EVENT_TYPE_JOB_COMPLETED
    schema_version: ClassVar[int] = JOB_COMPLETED_SCHEMA_VERSION

    event_id: str
    occurred_at: datetime
    job_id: JobId
    state: JobState
    finished_at: datetime
    retry_of: JobId | None
    submitter_id: SubjectId

    def __post_init__(self) -> None:
        if not self.state.is_terminal:
            raise ValueError("JobCompleted.state は終了状態でなければならない")

    def to_dict(self) -> dict[str, object]:
        """公開契約(contracts/job-completed-event.schema.json)の形に直列化する。"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": _iso_utc(self.occurred_at),
            "job_id": self.job_id,
            "state": self.state.value,
            "finished_at": _iso_utc(self.finished_at),
            "retry_of": self.retry_of,
            "submitter_id": self.submitter_id,
        }


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
