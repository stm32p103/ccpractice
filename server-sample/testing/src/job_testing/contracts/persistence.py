"""永続化のポートの契約テスト(contracts/ports.md「UnitOfWork」「JobRepository」「QueueRepository」)。

使い方: テストのクラスでこれらを継承し、`new_uow` フィクスチャ(引数なしで新しい UoW を返す関数)を定義する。
永続化は空の状態から始めること。core-persistence(実アダプタ)も同じクラスを継承して実行する。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest

from job_core.access.principal import PrincipalKind
from job_core.job.application.ports import UnitOfWork
from job_core.job.domain.audit import AuditOperation, AuditOutcome, AuditRecord
from job_core.job.domain.errors import ConcurrencyConflict
from job_core.job.domain.states import JobState
from job_core.job.domain.values import DuplicateKey, Reason
from job_core.shared.ids import JobId, RunnerId, SubjectId

from ._builders import T0, finish, make_job

NewUow = Callable[[], UnitOfWork]


def assert_queue_consistent(uow: UnitOfWork) -> None:
    """不変条件 2: 待機列の entries と、QUEUED のジョブが一致する。"""
    queue = uow.queue.get()
    queued = {job.job_id for job in uow.jobs.list_by_states([JobState.QUEUED], None, None).items}
    assert len(queue.entries) == len(set(queue.entries)), "待機列に重複がある"
    assert set(queue.entries) == queued, f"待機列 {queue.entries} と待機中のジョブ {sorted(queued)} が一致しない"


class UnitOfWorkContract:
    def test_commit_makes_all_changes_visible(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            job = make_job("j1")
            uow.jobs.add(job)
            queue = uow.queue.get()
            queue.append(job.job_id)
            uow.queue.save(queue)
            uow.commit()
        with new_uow() as uow:
            assert uow.jobs.get(JobId("j1")) is not None
            assert uow.queue.get().entries == ["j1"]
            assert_queue_consistent(uow)

    def test_uncommitted_changes_are_discarded(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.jobs.add(make_job("j1"))
            queue = uow.queue.get()
            queue.append(JobId("j1"))
            uow.queue.save(queue)
        with new_uow() as uow:
            assert uow.jobs.get(JobId("j1")) is None
            assert uow.queue.get().entries == []

    def test_exception_discards_changes(self, new_uow: NewUow) -> None:
        with pytest.raises(RuntimeError), new_uow() as uow:
            uow.jobs.add(make_job("j1"))
            raise RuntimeError("失敗")
        with new_uow() as uow:
            assert not uow.jobs.exists(JobId("j1"))

    def test_version_increments_on_commit(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.jobs.add(make_job("j1"))
            uow.commit()
        with new_uow() as uow:
            job = uow.jobs.get(JobId("j1"))
            assert job is not None
            first = job.version
            job.assign(RunnerId("r1"), T0)
            uow.jobs.save(job)
            uow.commit()
        with new_uow() as uow:
            job = uow.jobs.get(JobId("j1"))
            assert job is not None
            assert job.version == first + 1

    def test_concurrent_job_update_conflicts_and_rolls_back(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.jobs.add(make_job("j1"))
            uow.commit()
        first = new_uow()
        with first:
            job_a = first.jobs.get(JobId("j1"))
            assert job_a is not None
            with new_uow() as second:
                job_b = second.jobs.get(JobId("j1"))
                assert job_b is not None
                job_b.assign(RunnerId("r2"), T0)
                second.jobs.save(job_b)
                second.commit()
            job_a.assign(RunnerId("r1"), T0)
            first.jobs.save(job_a)
            first.audit.append(_record("a1", "j1"))
            with pytest.raises(ConcurrencyConflict):
                first.commit()
        with new_uow() as uow:
            job = uow.jobs.get(JobId("j1"))
            assert job is not None
            assert job.assigned_runner_id == "r2"
            assert uow.audit.history_of(JobId("j1")) == []

    def test_concurrent_queue_update_conflicts(self, new_uow: NewUow) -> None:
        first = new_uow()
        with first:
            queue_a = first.queue.get()
            with new_uow() as second:
                queue_b = second.queue.get()
                queue_b.append(JobId("b"))
                second.jobs.add(make_job("b"))
                second.queue.save(queue_b)
                second.commit()
            queue_a.append(JobId("a"))
            first.jobs.add(make_job("a"))
            first.queue.save(queue_a)
            with pytest.raises(ConcurrencyConflict):
                first.commit()
        with new_uow() as uow:
            assert uow.queue.get().entries == ["b"]
            assert not uow.jobs.exists(JobId("a"))

    def test_domain_events_are_written_to_outbox_on_commit(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.jobs.add(make_job("j1"))
            uow.commit()
        with new_uow() as uow:
            job = uow.jobs.get(JobId("j1"))
            assert job is not None
            job.cancel_queued(by=SubjectId("alice"), reason=Reason("不要"), at=T0, event_id="ev-1")
            uow.jobs.save(job)
            assert uow.outbox.fetch_pending(10) == []
            uow.commit()
        with new_uow() as uow:
            pending = uow.outbox.fetch_pending(10)
            assert [e.event.event_id for e in pending] == ["ev-1"]
            assert pending[0].event.state is JobState.CANCELLED

    def test_events_of_rolled_back_work_are_not_written(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.jobs.add(make_job("j1"))
            uow.commit()
        with new_uow() as uow:
            job = uow.jobs.get(JobId("j1"))
            assert job is not None
            job.cancel_queued(by=SubjectId("alice"), reason=None, at=T0, event_id="ev-1")
            uow.jobs.save(job)
        with new_uow() as uow:
            assert uow.outbox.fetch_pending(10) == []


class JobRepositoryContract:
    def test_roundtrip_preserves_every_field(self, new_uow: NewUow) -> None:
        job = make_job("j1", source="repo-1", revision="abc", retry_of="j0")
        job.assign(RunnerId("r1"), T0 + timedelta(seconds=1))
        job.request_abort(by=SubjectId("ops"), reason=Reason("止める"), at=T0 + timedelta(seconds=2))
        job.finish(
            runner_id=RunnerId("r1"),
            outcome=JobState.FAILED,
            summary=None,
            at=T0 + timedelta(seconds=3),
            event_id="ev-1",
        )
        with new_uow() as uow:
            uow.jobs.add(job)
            uow.commit()
        with new_uow() as uow:
            loaded = uow.jobs.get(JobId("j1"))
            assert loaded is not None
            for name in (
                "job_id",
                "definition",
                "submitter",
                "submitted_at",
                "state",
                "assigned_runner_id",
                "started_at",
                "finished_at",
                "result_summary",
                "cancellation",
                "retry_of",
            ):
                assert getattr(loaded, name) == getattr(job, name), name
            assert loaded.definition.payload.value == {"args": ["--flag"], "n": 1}

    def test_find_queued_by_duplicate_key_returns_only_queued(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.jobs.add(finish(make_job("done", source="s", revision="r"), JobState.SUCCEEDED, T0))
            uow.jobs.add(make_job("queued", source="s", revision="r"))
            uow.jobs.add(make_job("other", source="s", revision="r2"))
            uow.commit()
        with new_uow() as uow:
            found = uow.jobs.find_queued_by_duplicate_key(DuplicateKey("s", "r", "type-a"))
            assert found is not None and found.job_id == "queued"
            assert uow.jobs.find_queued_by_duplicate_key(DuplicateKey("s", "r", "type-b")) is None

    def test_find_unfinished_by_runner(self, new_uow: NewUow) -> None:
        running = make_job("run")
        running.assign(RunnerId("r1"), T0)
        with new_uow() as uow:
            uow.jobs.add(running)
            uow.jobs.add(finish(make_job("done"), JobState.SUCCEEDED, T0, runner="r2"))
            uow.commit()
        with new_uow() as uow:
            found = uow.jobs.find_unfinished_by_runner(RunnerId("r1"))
            assert found is not None and found.job_id == "run"
            assert uow.jobs.find_unfinished_by_runner(RunnerId("r2")) is None

    def test_find_retries_of(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            uow.jobs.add(make_job("orig"))
            uow.jobs.add(make_job("retry-2", retry_of="orig", at=T0 + timedelta(seconds=2)))
            uow.jobs.add(make_job("retry-1", retry_of="orig", at=T0 + timedelta(seconds=1)))
            uow.commit()
        with new_uow() as uow:
            assert uow.jobs.find_retries_of(JobId("orig")) == ["retry-1", "retry-2"]
            assert uow.jobs.find_retries_of(JobId("retry-1")) == []

    def test_list_finished_newest_first_with_paging(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            for i in range(5):
                uow.jobs.add(finish(make_job(f"f{i}"), JobState.SUCCEEDED, T0 + timedelta(minutes=i)))
            uow.jobs.add(make_job("q"))
            uow.commit()
        with new_uow() as uow:
            terminal = [JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED]
            first = uow.jobs.list_by_states(terminal, None, 2)
            assert [j.job_id for j in first.items] == ["f4", "f3"]
            assert first.next_cursor is not None
            second = uow.jobs.list_by_states(terminal, first.next_cursor, 2)
            third = uow.jobs.list_by_states(terminal, second.next_cursor, 2)
            assert [j.job_id for j in second.items] == ["f2", "f1"]
            assert [j.job_id for j in third.items] == ["f0"]
            assert third.next_cursor is None

    def test_delete_finished_before_only_removes_expired_terminal_jobs(self, new_uow: NewUow) -> None:
        old_running = make_job("old-running", at=T0 - timedelta(days=400))
        old_running.assign(RunnerId("r1"), T0 - timedelta(days=400))
        with new_uow() as uow:
            uow.jobs.add(finish(make_job("old"), JobState.FAILED, T0 - timedelta(days=400)))
            uow.jobs.add(finish(make_job("new"), JobState.FAILED, T0))
            uow.jobs.add(make_job("old-queued", at=T0 - timedelta(days=400)))
            uow.jobs.add(old_running)
            uow.commit()
        with new_uow() as uow:
            assert uow.jobs.delete_finished_before(T0 - timedelta(days=365)) == 1
            uow.commit()
        with new_uow() as uow:
            assert not uow.jobs.exists(JobId("old"))
            for kept in ("new", "old-queued", "old-running"):
                assert uow.jobs.exists(JobId(kept)), kept


class QueueRepositoryContract:
    def test_empty_queue(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            assert uow.queue.get().entries == []

    def test_order_is_preserved(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            queue = uow.queue.get()
            for job_id in ("c", "a", "b"):
                uow.jobs.add(make_job(job_id))
                queue.append(JobId(job_id))
            uow.queue.save(queue)
            uow.commit()
        with new_uow() as uow:
            queue = uow.queue.get()
            assert queue.entries == ["c", "a", "b"]
            queue.remove(JobId("a"))
            queue.entries.insert(0, JobId("a"))
            uow.queue.save(queue)
            uow.commit()
        with new_uow() as uow:
            assert uow.queue.get().entries == ["a", "c", "b"]


def _record(record_id: str, job_id: str) -> AuditRecord:
    return AuditRecord(
        record_id=record_id,
        occurred_at=T0,
        actor=SubjectId("alice"),
        actor_kind=PrincipalKind.HUMAN,
        operation=AuditOperation.SUBMIT,
        job_id=JobId(job_id),
        outcome=AuditOutcome.SUCCEEDED,
    )
