"""SqlUnitOfWork(contracts/ports.md「UnitOfWork」。001・002 のポートの束)。

すべて確定するか何も確定しない。commit は 1 つのトランザクションで、version の検査(楽観的排他)と反映を行い、
衝突は ConcurrencyConflict にする。確定していない変更(pending)は、commit しなければ捨てる。
集約に積まれたイベントは、commit の中でアウトボックスへ書く。
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Self

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from job_core.job.domain.events import JobCompleted

from .models import jobs
from .repositories.audit import SqlAuditLog, SqlOutbox
from .repositories.jobs import TERMINAL_VALUES, SqlJobRepository, SqlQueueRepository
from .repositories.runners import (
    SqlAllowlistRepository,
    SqlLeaseRepository,
    SqlRunnerRepository,
    SqlRunnerTokenRepository,
)
from .tracking import run_commit


class SqlUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.jobs = SqlJobRepository(engine)
        self.queue = SqlQueueRepository(engine)
        self.audit = SqlAuditLog(engine)
        self.outbox = SqlOutbox(engine)
        self.runners = SqlRunnerRepository(engine)
        self.leases = SqlLeaseRepository(engine)
        self.tokens = SqlRunnerTokenRepository(engine)
        self.allowlist = SqlAllowlistRepository(engine)
        self._committed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None  # commit されていなければ、何も確定しない(pending を捨てるだけ)

    def commit(self) -> None:
        if self._committed:
            raise RuntimeError("この UoW は確定済み")
        events: list[JobCompleted] = list(self.outbox.pending)
        for job in self.jobs.tracked.pending.values():
            events.extend(job.pull_events())

        def action(conn: Connection) -> None:
            self.jobs.tracked.apply(conn)
            for cutoff in self.jobs.delete_cutoffs:
                conn.execute(sa.delete(jobs).where(jobs.c.state.in_(TERMINAL_VALUES), jobs.c.finished_at < cutoff))
            self.queue.singleton.apply(conn)
            self.runners.tracked.apply(conn)
            self.leases.tracked.apply(conn)
            self.tokens.tracked.apply(conn)
            self.allowlist.singleton.apply(conn)
            self.audit.apply(conn)
            SqlOutbox.insert(conn, events)

        run_commit(self._engine, action)
        self._committed = True


def sql_uow_factory(engine: Engine) -> Callable[[], SqlUnitOfWork]:
    """`CoreDependencies.uow_factory` に渡す、UoW の生成関数。"""
    return lambda: SqlUnitOfWork(engine)
