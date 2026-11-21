"""ポート(contracts/ports.md)。振る舞いの約束は contracts/ports.md を正とする。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

from job_core.job.domain.audit import AuditOperation, AuditOutcome, AuditRecord
from job_core.job.domain.events import JobCompleted
from job_core.job.domain.job import Job
from job_core.job.domain.queue import Queue
from job_core.job.domain.states import JobState
from job_core.job.domain.values import DuplicateKey, RunnerRequirement
from job_core.shared.ids import JobId, RunnerId, SubjectId
from job_core.shared.ports import Clock, IdGenerator


@dataclass(frozen=True)
class Page[T]:
    """頁送りの結果。next_cursor が None なら最後の頁。"""

    items: list[T]
    next_cursor: str | None = None


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"


@dataclass
class OutboxEntry:
    """アウトボックスの 1 件(data-model.md OutboxEntry.event、.status、.recorded_at、.dispatched_at、.attempts)。"""

    event: JobCompleted
    status: OutboxStatus
    recorded_at: datetime
    dispatched_at: datetime | None = None
    attempts: int = 0


@dataclass(frozen=True)
class AuditFilter:
    since: datetime | None = None
    until: datetime | None = None
    job_id: JobId | None = None
    actor: SubjectId | None = None
    operation: AuditOperation | None = None
    outcome: AuditOutcome | None = None

    def matches(self, record: AuditRecord) -> bool:
        return (
            (self.since is None or record.occurred_at >= self.since)
            and (self.until is None or record.occurred_at < self.until)
            and (self.job_id is None or record.job_id == self.job_id)
            and (self.actor is None or record.actor == self.actor)
            and (self.operation is None or record.operation is self.operation)
            and (self.outcome is None or record.outcome is self.outcome)
        )


class JobRepository(Protocol):
    def get(self, job_id: JobId) -> Job | None: ...
    def add(self, job: Job) -> None: ...
    def save(self, job: Job) -> None: ...
    def find_queued_by_duplicate_key(self, key: DuplicateKey) -> Job | None: ...
    def find_unfinished_by_runner(self, runner_id: RunnerId) -> Job | None: ...
    def find_retries_of(self, job_id: JobId) -> list[JobId]: ...
    def exists(self, job_id: JobId) -> bool: ...
    def list_by_states(self, states: Iterable[JobState], cursor: str | None, limit: int | None) -> Page[Job]: ...
    def delete_finished_before(self, cutoff: datetime) -> int: ...


class QueueRepository(Protocol):
    def get(self) -> Queue: ...
    def save(self, queue: Queue) -> None: ...


class AuditLog(Protocol):
    def append(self, record: AuditRecord) -> None: ...
    def append_denied(self, record: AuditRecord) -> None: ...
    def history_of(self, job_id: JobId) -> list[AuditRecord]: ...
    def query(self, audit_filter: AuditFilter, cursor: str | None, limit: int) -> Page[AuditRecord]: ...
    def delete_before(self, cutoff: datetime) -> int: ...


class Outbox(Protocol):
    def add(self, event: JobCompleted) -> None: ...
    def fetch_pending(self, limit: int) -> list[OutboxEntry]: ...
    def mark_dispatched(self, event_id: str, at: datetime) -> None: ...
    def record_attempt(self, event_id: str, at: datetime) -> None: ...


class UnitOfWork(Protocol):
    @property
    def jobs(self) -> JobRepository: ...
    @property
    def queue(self) -> QueueRepository: ...
    @property
    def audit(self) -> AuditLog: ...
    @property
    def outbox(self) -> Outbox: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]


class RunnerEligibility(Protocol):
    """ランナー要件の判定(002 が実装する)。副作用を持たない。"""

    def any_registered_runner_may_satisfy(self, requirement: RunnerRequirement) -> bool: ...
    def runner_satisfies(self, runner_id: RunnerId, requirement: RunnerRequirement) -> bool: ...


@dataclass(frozen=True)
class CoreDependencies:
    """ユースケースが使うポートの束。起動時の設定で実装を差し替える(憲章 原則 1)。"""

    uow_factory: UnitOfWorkFactory
    eligibility: RunnerEligibility
    clock: Clock
    ids: IdGenerator
    max_conflict_retries: int = field(default=3)
