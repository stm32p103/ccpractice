"""監査ログとアウトボックスのポートの契約テスト(contracts/ports.md「AuditLog」「Outbox」)。

使い方は persistence.py と同じ(`new_uow` フィクスチャを定義する)。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from job_core.access.principal import PrincipalKind
from job_core.job.application.ports import AuditFilter, OutboxStatus
from job_core.job.domain.audit import AuditOperation, AuditOutcome, AuditRecord, Denial
from job_core.job.domain.events import JobCompleted
from job_core.job.domain.states import JobState
from job_core.shared.ids import JobId, SubjectId

from ._builders import T0
from .persistence import NewUow


def record(
    record_id: str,
    *,
    at: datetime = T0,
    job_id: str | None = "j1",
    outcome: AuditOutcome = AuditOutcome.SUCCEEDED,
    operation: AuditOperation = AuditOperation.SUBMIT,
    actor: str = "alice",
) -> AuditRecord:
    return AuditRecord(
        record_id=record_id,
        occurred_at=at,
        actor=SubjectId(actor),
        actor_kind=PrincipalKind.HUMAN,
        operation=operation,
        job_id=JobId(job_id) if job_id else None,
        outcome=outcome,
        after={"state": "queued"},
        denial=Denial("permission_denied", ("queue.schedule",)) if outcome is AuditOutcome.DENIED else None,
    )


def event(event_id: str, job_id: str = "j1") -> JobCompleted:
    return JobCompleted(
        event_id=event_id,
        occurred_at=T0,
        job_id=JobId(job_id),
        state=JobState.SUCCEEDED,
        finished_at=T0,
        retry_of=None,
        submitter_id=SubjectId("alice"),
    )


class AuditLogContract:
    def test_append_is_visible_only_after_commit(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.audit.append(record("a1"))
        with new_uow() as uow:
            assert uow.audit.history_of(JobId("j1")) == []
            uow.audit.append(record("a1"))
            uow.commit()
        with new_uow() as uow:
            assert [r.record_id for r in uow.audit.history_of(JobId("j1"))] == ["a1"]

    def test_append_denied_survives_rollback(self, new_uow: NewUow) -> None:
        with pytest.raises(RuntimeError), new_uow() as uow:
            uow.audit.append_denied(record("d1", outcome=AuditOutcome.DENIED))
            raise RuntimeError("本体の失敗")
        with new_uow() as uow:
            page = uow.audit.query(AuditFilter(outcome=AuditOutcome.DENIED), None, 10)
            assert [r.record_id for r in page.items] == ["d1"]
            assert page.items[0].denial == Denial("permission_denied", ("queue.schedule",))

    def test_history_excludes_denied_and_is_ordered(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.audit.append(record("a2", at=T0 + timedelta(seconds=2)))
            uow.audit.append(record("a1", at=T0 + timedelta(seconds=1)))
            uow.audit.append(record("other", job_id="j2"))
            uow.audit.append_denied(record("d1", outcome=AuditOutcome.DENIED))
            uow.commit()
        with new_uow() as uow:
            assert [r.record_id for r in uow.audit.history_of(JobId("j1"))] == ["a1", "a2"]

    def test_query_filters_and_pages(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            for i in range(5):
                uow.audit.append(record(f"a{i}", at=T0 + timedelta(seconds=i), actor="alice" if i % 2 else "bob"))
            uow.commit()
        with new_uow() as uow:
            first = uow.audit.query(AuditFilter(), None, 3)
            assert [r.record_id for r in first.items] == ["a0", "a1", "a2"]
            rest = uow.audit.query(AuditFilter(), first.next_cursor, 3)
            assert [r.record_id for r in rest.items] == ["a3", "a4"]
            assert rest.next_cursor is None
            alice = uow.audit.query(AuditFilter(actor=SubjectId("alice")), None, 10)
            assert [r.record_id for r in alice.items] == ["a1", "a3"]
            window = uow.audit.query(
                AuditFilter(since=T0 + timedelta(seconds=1), until=T0 + timedelta(seconds=3)), None, 10
            )
            assert [r.record_id for r in window.items] == ["a1", "a2"]

    def test_delete_before_removes_only_old_records(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.audit.append(record("old", at=T0 - timedelta(days=2000)))
            uow.audit.append(record("new", at=T0))
            uow.commit()
        with new_uow() as uow:
            assert uow.audit.delete_before(T0 - timedelta(days=1095)) == 1
            uow.commit()
        with new_uow() as uow:
            assert [r.record_id for r in uow.audit.query(AuditFilter(), None, 10).items] == ["new"]


class OutboxContract:
    def test_pending_is_returned_until_dispatched(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.outbox.add(event("e1"))
            uow.outbox.add(event("e2"))
            uow.commit()
        with new_uow() as uow:
            assert [e.event.event_id for e in uow.outbox.fetch_pending(10)] == ["e1", "e2"]
            assert [e.event.event_id for e in uow.outbox.fetch_pending(10)] == ["e1", "e2"]
            uow.outbox.record_attempt("e1", T0)
            uow.outbox.mark_dispatched("e1", T0 + timedelta(seconds=1))
        with new_uow() as uow:
            pending = uow.outbox.fetch_pending(10)
            assert [e.event.event_id for e in pending] == ["e2"]
            assert all(e.status is OutboxStatus.PENDING for e in pending)

    def test_fetch_respects_limit(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            for i in range(3):
                uow.outbox.add(event(f"e{i}"))
            uow.commit()
        with new_uow() as uow:
            assert len(uow.outbox.fetch_pending(2)) == 2

    def test_event_id_is_unique(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.outbox.add(event("e1"))
            uow.commit()
        with pytest.raises(Exception), new_uow() as uow:  # noqa: B017 - 実装ごとに例外の型が異なる
            uow.outbox.add(event("e1"))
            uow.commit()
        with new_uow() as uow:
            assert len(uow.outbox.fetch_pending(10)) == 1
