"""監査ログとアウトボックスのリポジトリ(contracts/ports.md「AuditLog」「Outbox」)。

監査ログは追記専用(更新はなく、削除は保持期間の削除だけ)。`append_denied` は、呼び出し時点で独立に確定する。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from job_core.job.application.ports import AuditFilter, OutboxEntry, OutboxStatus, Page
from job_core.job.domain.audit import AuditOutcome, AuditRecord
from job_core.job.domain.events import JobCompleted
from job_core.shared.ids import JobId

from ..codec import decode, encode
from ..models import audit_log, outbox
from .jobs import parse_offset


def audit_row(record: AuditRecord) -> dict[str, object]:
    return {
        "record_id": record.record_id,
        "occurred_at": record.occurred_at,
        "job_id": record.job_id,
        "actor": record.actor,
        "operation": record.operation.value,
        "outcome": record.outcome.value,
        "runner_id": record.runner_id,
        "doc": encode(record),
    }


def _conditions(f: AuditFilter) -> list[sa.ColumnElement[bool]]:
    c: list[sa.ColumnElement[bool]] = []
    t = audit_log.c
    if f.since is not None:
        c.append(t.occurred_at >= f.since)
    if f.until is not None:
        c.append(t.occurred_at < f.until)
    if f.job_id is not None:
        c.append(t.job_id == f.job_id)
    if f.actor is not None:
        c.append(t.actor == f.actor)
    if f.operation is not None:
        c.append(t.operation == f.operation.value)
    if f.outcome is not None:
        c.append(t.outcome == f.outcome.value)
    if f.runner_id is not None:
        c.append(t.runner_id == f.runner_id)
    return c


class SqlAuditLog:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.pending: list[AuditRecord] = []
        self.delete_cutoffs: list[datetime] = []

    def append(self, record: AuditRecord) -> None:
        self.pending.append(record)

    def append_denied(self, record: AuditRecord) -> None:
        with self._engine.begin() as conn:
            conn.execute(sa.insert(audit_log).values(**audit_row(record)))

    def _select(
        self, conditions: list[sa.ColumnElement[bool]], predicate: AuditFilter | None, extra: object = None
    ) -> list[AuditRecord]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(audit_log.c.doc).where(*conditions).order_by(audit_log.c.occurred_at, audit_log.c.record_id)
            ).all()
        records = [decode(AuditRecord, r.doc) for r in rows]
        for cutoff in self.delete_cutoffs:
            records = [r for r in records if r.occurred_at >= cutoff]
        records += [r for r in self.pending if predicate is None or predicate.matches(r)]
        return sorted(records, key=lambda r: (r.occurred_at, r.record_id))

    def history_of(self, job_id: JobId) -> list[AuditRecord]:
        records = self._select(
            [audit_log.c.job_id == job_id, audit_log.c.outcome == AuditOutcome.SUCCEEDED.value], None
        )
        return [r for r in records if r.job_id == job_id and r.outcome is AuditOutcome.SUCCEEDED]

    def query(self, audit_filter: AuditFilter, cursor: str | None, limit: int) -> Page[AuditRecord]:
        start = parse_offset(cursor)
        if not self.pending and not self.delete_cutoffs:
            stmt = (
                sa.select(audit_log.c.doc)
                .where(*_conditions(audit_filter))
                .order_by(audit_log.c.occurred_at, audit_log.c.record_id)
                .offset(start)
                .limit(limit + 1)
            )
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).all()
            items = [decode(AuditRecord, r.doc) for r in rows]
            if len(items) > limit:
                return Page(items[:limit], str(start + limit))
            return Page(items, None)
        records = self._select(_conditions(audit_filter), audit_filter)
        end = start + limit
        return Page(records[start:end], str(end) if end < len(records) else None)

    def delete_before(self, cutoff: datetime) -> int:
        with self._engine.connect() as conn:
            count = conn.execute(
                sa.select(sa.func.count()).select_from(audit_log).where(audit_log.c.occurred_at < cutoff)
            ).scalar_one()
        self.delete_cutoffs.append(cutoff)
        return int(count)

    def apply(self, conn: Connection) -> None:
        for cutoff in self.delete_cutoffs:
            conn.execute(sa.delete(audit_log).where(audit_log.c.occurred_at < cutoff))
        for record in self.pending:
            conn.execute(sa.insert(audit_log).values(**audit_row(record)))


class SqlOutbox:
    """add は UoW の commit で確定する。取り出し・配信済みの記録は、配信側の操作として即時に確定する。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.pending: list[JobCompleted] = []

    def add(self, event: JobCompleted) -> None:
        self.pending.append(event)

    def fetch_pending(self, limit: int) -> list[OutboxEntry]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(outbox)
                .where(outbox.c.status == OutboxStatus.PENDING.value)
                .order_by(outbox.c.seq)
                .limit(limit)
            ).all()
        return [
            OutboxEntry(
                event=decode(JobCompleted, r.doc),
                status=OutboxStatus(r.status),
                recorded_at=r.recorded_at,
                dispatched_at=r.dispatched_at,
                attempts=r.attempts,
            )
            for r in rows
        ]

    def mark_dispatched(self, event_id: str, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.update(outbox)
                .where(outbox.c.event_id == event_id)
                .values(status=OutboxStatus.DISPATCHED.value, dispatched_at=at)
            )

    def record_attempt(self, event_id: str, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(sa.update(outbox).where(outbox.c.event_id == event_id).values(attempts=outbox.c.attempts + 1))

    @staticmethod
    def insert(conn: Connection, events: list[JobCompleted]) -> None:
        for event in events:
            exists = conn.execute(sa.select(sa.literal(1)).where(outbox.c.event_id == event.event_id)).first()
            if exists:
                raise ValueError(f"イベント {event.event_id} は既にアウトボックスにある")
            conn.execute(
                sa.insert(outbox).values(
                    event_id=event.event_id,
                    status=OutboxStatus.PENDING.value,
                    recorded_at=event.occurred_at,
                    doc=encode(event),
                )
            )
