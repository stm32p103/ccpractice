"""メモリ上の Unit of Work とリポジトリ(contracts/ports.md の約束 1〜5 の Fake)。
002 の runner のリポジトリ(runners、leases、tokens、allowlist)も、同じ UoW で確定する(runner_repositories.py)。

- 確定した状態は InMemoryStore が持つ。UoW は読み込んだ集約の複製を扱い、commit で version を比較して確定する。
- 集約に積まれたイベントは、commit の中でアウトボックスへ PENDING として書く。
- append_denied は、呼び出し時点で独立に確定する。
- テスト用に「次の commit の直前に別の操作を割り込ませる」フック(inject_before_next_commit)を持つ。
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterable
from datetime import datetime
from types import TracebackType
from typing import Self

from job_core.job.application.ports import AuditFilter, OutboxEntry, OutboxStatus, Page
from job_core.job.domain.audit import AuditOutcome, AuditRecord
from job_core.job.domain.errors import ConcurrencyConflict
from job_core.job.domain.events import JobCompleted
from job_core.job.domain.job import Job
from job_core.job.domain.queue import Queue
from job_core.job.domain.states import JobState
from job_core.job.domain.values import DuplicateKey
from job_core.shared.ids import JobId, RunnerId

from .runner_repositories import RunnerRepositories, RunnerStoreState


class InMemoryStore:
    """確定した状態。複数の UoW から共有される。"""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.jobs: dict[JobId, Job] = {}
        self.queue = Queue()
        self.audit: list[AuditRecord] = []
        self.outbox: dict[str, OutboxEntry] = {}
        self.runner_state = RunnerStoreState()
        self._before_commit: list[Callable[[], None]] = []
        self.commit_count = 0

    def new_unit_of_work(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(self)

    def inject_before_next_commit(self, action: Callable[[], None]) -> None:
        """次に commit する UoW の、確定の直前に action を実行する(同時実行の再現用。1 回だけ)。"""
        self._before_commit.append(action)

    def take_before_commit_actions(self) -> list[Callable[[], None]]:
        with self.lock:
            actions, self._before_commit = self._before_commit, []
            return actions


def _page(items: list[object], cursor: str | None, limit: int | None) -> tuple[list[object], str | None]:
    start = int(cursor) if cursor else 0
    if limit is None:
        return items[start:], None
    end = start + limit
    return items[start:end], (str(end) if end < len(items) else None)


class InMemoryJobRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self.pending: dict[JobId, Job] = {}
        self.loaded_versions: dict[JobId, int] = {}
        self.new_ids: set[JobId] = set()
        self.delete_cutoffs: list[datetime] = []

    # 読み込み ---------------------------------------------------------------

    def _merged(self) -> dict[JobId, Job]:
        merged = dict(self._store.jobs)
        merged.update(self.pending)
        for cutoff in self.delete_cutoffs:
            for job_id in [j for j, job in merged.items() if _expired(job, cutoff)]:
                del merged[job_id]
        return merged

    def get(self, job_id: JobId) -> Job | None:
        if job_id in self.pending:
            return self.pending[job_id]
        job = self._merged().get(job_id)
        if job is None:
            return None
        loaded = copy.deepcopy(job)
        self.loaded_versions[job_id] = loaded.version
        self.pending[job_id] = loaded
        return loaded

    def exists(self, job_id: JobId) -> bool:
        return job_id in self._merged()

    def find_queued_by_duplicate_key(self, key: DuplicateKey) -> Job | None:
        for job in self._merged().values():
            if job.state is JobState.QUEUED and job.definition.duplicate_key() == key:
                return self.get(job.job_id)
        return None

    def find_unfinished_by_runner(self, runner_id: RunnerId) -> Job | None:
        for job in self._merged().values():
            if job.assigned_runner_id == runner_id and not job.state.is_terminal:
                return self.get(job.job_id)
        return None

    def find_retries_of(self, job_id: JobId) -> list[JobId]:
        retries = [job for job in self._merged().values() if job.retry_of == job_id]
        return [job.job_id for job in sorted(retries, key=lambda j: (j.submitted_at, j.job_id))]

    def list_by_states(self, states: Iterable[JobState], cursor: str | None, limit: int | None) -> Page[Job]:
        wanted = set(states)
        jobs = [job for job in self._merged().values() if job.state in wanted]
        if wanted <= {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            jobs.sort(key=lambda j: (j.finished_at or j.submitted_at, j.job_id), reverse=True)
        else:
            jobs.sort(key=lambda j: (j.submitted_at, j.job_id))
        items, next_cursor = _page(list(jobs), cursor, limit)
        return Page([copy.deepcopy(j) for j in items if isinstance(j, Job)], next_cursor)

    # 変更 -------------------------------------------------------------------

    def add(self, job: Job) -> None:
        if job.job_id in self._merged():
            raise ValueError(f"ジョブ {job.job_id} は既にある")
        self.pending[job.job_id] = job
        self.new_ids.add(job.job_id)

    def save(self, job: Job) -> None:
        if job.job_id not in self.pending:
            raise ValueError("save は、この UoW で読み込んだか追加したジョブにだけ使う")
        self.pending[job.job_id] = job

    def delete_finished_before(self, cutoff: datetime) -> int:
        count = sum(1 for job in self._merged().values() if _expired(job, cutoff))
        self.delete_cutoffs.append(cutoff)
        return count


def _expired(job: Job, cutoff: datetime) -> bool:
    return job.state.is_terminal and job.finished_at is not None and job.finished_at < cutoff


class InMemoryQueueRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self.pending: Queue | None = None
        self.loaded_version: int | None = None

    def get(self) -> Queue:
        if self.pending is None:
            self.pending = copy.deepcopy(self._store.queue)
            self.loaded_version = self.pending.version
        return self.pending

    def save(self, queue: Queue) -> None:
        if self.pending is None or queue is not self.pending:
            raise ValueError("save は、この UoW で get した待機列にだけ使う")


class InMemoryAuditLog:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self.pending: list[AuditRecord] = []
        self.delete_cutoffs: list[datetime] = []

    def _merged(self) -> list[AuditRecord]:
        records = [*self._store.audit, *self.pending]
        for cutoff in self.delete_cutoffs:
            records = [r for r in records if r.occurred_at >= cutoff]
        return records

    def append(self, record: AuditRecord) -> None:
        self.pending.append(record)

    def append_denied(self, record: AuditRecord) -> None:
        with self._store.lock:
            self._store.audit.append(record)

    def history_of(self, job_id: JobId) -> list[AuditRecord]:
        records = [r for r in self._merged() if r.job_id == job_id and r.outcome is AuditOutcome.SUCCEEDED]
        return sorted(records, key=lambda r: (r.occurred_at, r.record_id))

    def query(self, audit_filter: AuditFilter, cursor: str | None, limit: int) -> Page[AuditRecord]:
        records = sorted(
            (r for r in self._merged() if audit_filter.matches(r)), key=lambda r: (r.occurred_at, r.record_id)
        )
        items, next_cursor = _page(list(records), cursor, limit)
        return Page([r for r in items if isinstance(r, AuditRecord)], next_cursor)

    def delete_before(self, cutoff: datetime) -> int:
        count = sum(1 for r in self._merged() if r.occurred_at < cutoff)
        self.delete_cutoffs.append(cutoff)
        return count


class InMemoryOutbox:
    """add は UoW の commit で確定する。取り出し・配信済みの記録は、配信側の操作として即時に確定する。"""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self.pending: list[JobCompleted] = []

    def add(self, event: JobCompleted) -> None:
        self.pending.append(event)

    def fetch_pending(self, limit: int) -> list[OutboxEntry]:
        with self._store.lock:
            entries = [e for e in self._store.outbox.values() if e.status is OutboxStatus.PENDING]
            return [copy.deepcopy(e) for e in entries[:limit]]

    def mark_dispatched(self, event_id: str, at: datetime) -> None:
        with self._store.lock:
            entry = self._store.outbox[event_id]
            entry.status = OutboxStatus.DISPATCHED
            entry.dispatched_at = at

    def record_attempt(self, event_id: str, at: datetime) -> None:
        with self._store.lock:
            self._store.outbox[event_id].attempts += 1


class InMemoryUnitOfWork:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self.jobs = InMemoryJobRepository(store)
        self.queue = InMemoryQueueRepository(store)
        self.audit = InMemoryAuditLog(store)
        self.outbox = InMemoryOutbox(store)
        self._runner = RunnerRepositories(store.runner_state)
        self.runners = self._runner.runners
        self.leases = self._runner.leases
        self.tokens = self._runner.tokens
        self.allowlist = self._runner.allowlist
        self._committed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # commit されていなければ、何も確定しない(pending を捨てるだけ)
        return None

    def commit(self) -> None:
        if self._committed:
            raise RuntimeError("この UoW は確定済み")
        for action in self._store.take_before_commit_actions():
            action()
        store = self._store
        with store.lock:
            self._check_versions()
            self._apply()
            store.commit_count += 1
        self._committed = True

    def _check_versions(self) -> None:
        store = self._store
        for job_id, loaded in self.jobs.loaded_versions.items():
            current = store.jobs.get(job_id)
            if current is None or current.version != loaded:
                raise ConcurrencyConflict(f"ジョブ {job_id} が同時に更新された")
        for job_id in self.jobs.new_ids:
            if job_id in store.jobs:
                raise ConcurrencyConflict(f"ジョブ {job_id} が同時に追加された")
        if self.queue.loaded_version is not None and store.queue.version != self.queue.loaded_version:
            raise ConcurrencyConflict("待機列が同時に更新された")
        self._runner.check()

    def _apply(self) -> None:
        store = self._store
        now_events: list[JobCompleted] = list(self.outbox.pending)
        for job_id, job in self.jobs.pending.items():
            now_events.extend(job.pull_events())
            unchanged = job_id in self.jobs.loaded_versions and _same(store.jobs[job_id], job)
            if unchanged:
                continue
            job.version += 1
            store.jobs[job_id] = copy.deepcopy(job)
        for cutoff in self.jobs.delete_cutoffs:
            for job_id in [j for j, job in store.jobs.items() if _expired(job, cutoff)]:
                del store.jobs[job_id]
        if self.queue.pending is not None and self.queue.pending.entries != store.queue.entries:
            self.queue.pending.version += 1
            store.queue = copy.deepcopy(self.queue.pending)
        self._runner.apply()
        for cutoff in self.audit.delete_cutoffs:
            store.audit = [r for r in store.audit if r.occurred_at >= cutoff]
        store.audit.extend(self.audit.pending)
        for event in now_events:
            if event.event_id in store.outbox:
                raise ValueError(f"イベント {event.event_id} は既にアウトボックスにある")
            store.outbox[event.event_id] = OutboxEntry(
                event=event, status=OutboxStatus.PENDING, recorded_at=event.occurred_at
            )


def _same(stored: Job, working: Job) -> bool:
    fields = (
        "state",
        "assigned_runner_id",
        "started_at",
        "finished_at",
        "result_summary",
        "cancellation",
        "retry_of",
        "definition",
        "submitter",
        "submitted_at",
    )
    return all(getattr(stored, f) == getattr(working, f) for f in fields)
