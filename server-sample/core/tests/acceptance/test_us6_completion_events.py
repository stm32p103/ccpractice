"""US6 — ジョブ完了イベント(spec US6-5、US6-6、SC-008)。"""

from __future__ import annotations

from job_core.job.application import JobState

from .conftest import Env


def pending_events(env: Env) -> list:  # type: ignore[type-arg]
    with env.core.new_uow() as uow:
        return uow.outbox.fetch_pending(1000)


def test_us6_5_every_kind_of_termination_emits_one_event(env: Env) -> None:
    succeeded = env.submit().job_id
    env.run(succeeded)
    env.finish(succeeded, JobState.SUCCEEDED)
    failed = env.submit().job_id
    env.run(failed)
    env.finish(failed, JobState.FAILED)
    cancelled = env.submit().job_id
    env.core.cancel(env.alice, job_id=cancelled)
    aborted = env.submit().job_id
    env.run(aborted)
    env.core.cancel(env.alice, job_id=aborted, reason="止めて")
    env.core.confirm_stopped(env.runner1, runner_id="R1", job_id=aborted)

    events = {entry.event.job_id: entry.event for entry in pending_events(env)}
    assert {job_id: e.state for job_id, e in events.items()} == {
        succeeded: JobState.SUCCEEDED,
        failed: JobState.FAILED,
        cancelled: JobState.CANCELLED,
        aborted: JobState.CANCELLED,
    }
    assert len(pending_events(env)) == 4
    for event in events.values():
        assert set(event.to_dict()) == {
            "event_id",
            "event_type",
            "schema_version",
            "occurred_at",
            "job_id",
            "state",
            "finished_at",
            "retry_of",
            "submitter_id",
        }


def test_us6_6_events_survive_until_receiver_recovers(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    env.finish(job_id)
    assert env.job(job_id).state is JobState.SUCCEEDED  # 終了は配信と無関係に確定している

    # 受け手が受け取れない間: 取り出しても配信済みにしない → 何度でも同じイベントが返る
    with env.core.new_uow() as uow:
        first = uow.outbox.fetch_pending(10)
        uow.outbox.record_attempt(first[0].event.event_id, env.core.clock.now())
    second = pending_events(env)
    assert [e.event.event_id for e in second] == [e.event.event_id for e in first]
    assert second[0].attempts == 1

    # 受け手の復旧後: 配信できたら配信済みにする
    with env.core.new_uow() as uow:
        uow.outbox.mark_dispatched(second[0].event.event_id, env.core.clock.now())
    assert pending_events(env) == []


def test_edge_events_are_not_emitted_for_non_terminal_changes(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    env.core.cancel(env.alice, job_id=job_id, reason="止めて")
    assert pending_events(env) == []


def test_edge_retry_link_is_in_event(env: Env) -> None:
    original = env.submit().job_id
    env.core.cancel(env.alice, job_id=original)
    retried = env.core.retry(env.bob, job_id=original).job_id
    env.core.cancel(env.bob, job_id=retried)
    event = next(e.event for e in pending_events(env) if e.event.job_id == retried)
    assert event.retry_of == original
    assert event.submitter_id == "bob"
