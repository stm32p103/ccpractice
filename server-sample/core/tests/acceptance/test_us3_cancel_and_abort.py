"""US3 — 待機中のジョブの取り消しと、実行中のジョブの強制中断(spec US3-1〜US3-6 とエッジケース)。"""

from __future__ import annotations

import pytest

from job_core.job.application import (
    AbortAlreadyRequested,
    AuditOperation,
    InvalidStateTransition,
    JobNotFound,
    JobState,
    PermissionDenied,
    ReasonRequired,
    RunnerMismatch,
)
from job_core.job.domain.job import CancellationKind

from .conftest import Env


def test_us3_1_own_queued_job_is_cancelled_and_queue_closes_gap(env: Env) -> None:
    a, b, c = env.submit_many(3)
    result = env.core.cancel(env.alice, job_id=a)
    assert result.state is JobState.CANCELLED
    assert not result.abort_pending
    assert env.queue_ids() == [b, c]
    assert env.assign() == b  # 取り消したジョブは割り当てられない
    job = env.job(a)
    assert job.cancellation is not None and job.cancellation.kind is CancellationKind.QUEUED_CANCEL
    env.assert_consistent()


def test_us3_2_force_abort_records_request_then_confirm(env: Env) -> None:
    job_id = env.submit(env.bob).job_id
    env.run(job_id)
    result = env.core.cancel(env.aborter, job_id=job_id, reason="機器の保守のため")
    assert result.state is JobState.RUNNING and result.abort_pending
    job = env.job(job_id)
    assert job.cancellation is not None
    assert (job.cancellation.requested_by, job.cancellation.reason) == ("aborter", job.cancellation.reason)
    assert job.cancellation.reason is not None and job.cancellation.reason.value == "機器の保守のため"
    finished = env.core.confirm_stopped(env.runner1, runner_id="R1", job_id=job_id)
    assert finished.state is JobState.CANCELLED
    with env.core.new_uow() as uow:
        events = [e.event for e in uow.outbox.fetch_pending(10) if e.event.job_id == job_id]
    assert [e.state for e in events] == [JobState.CANCELLED]


def test_us3_3_without_permission_others_job_cannot_be_cancelled(env: Env) -> None:
    job_id = env.submit(env.bob).job_id
    with pytest.raises(PermissionDenied):
        env.core.cancel(env.alice, job_id=job_id)
    assert env.job(job_id).state is JobState.QUEUED
    assert [r.operation for r in env.denied_records()] == [AuditOperation.CANCEL_QUEUED]


def test_us3_4_cancel_permission_cancels_others_queued_job(env: Env) -> None:
    job_id = env.submit(env.bob).job_id
    env.core.cancel(env.canceller, job_id=job_id)
    assert env.job(job_id).state is JobState.CANCELLED
    assert env.queue_ids() == []


def test_us3_5_permissions_are_separate(env: Env) -> None:
    running = env.submit(env.bob).job_id
    env.run(running)
    queued = env.submit(env.bob).job_id
    with pytest.raises(PermissionDenied):
        env.core.cancel(env.canceller, job_id=running, reason="x")
    assert env.job(running).state is JobState.RUNNING
    with pytest.raises(PermissionDenied):
        env.core.cancel(env.aborter, job_id=queued)
    assert env.job(queued).state is JobState.QUEUED


@pytest.mark.parametrize("final", [JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED])
def test_us3_6_finished_job_cannot_be_cancelled(env: Env, final: JobState) -> None:
    job_id = env.submit().job_id
    if final is JobState.CANCELLED:
        env.core.cancel(env.alice, job_id=job_id)
    else:
        env.run(job_id)
        env.finish(job_id, final)
    with pytest.raises(InvalidStateTransition):
        env.core.cancel(env.alice, job_id=job_id, reason="x")
    with pytest.raises(InvalidStateTransition):
        env.core.cancel(env.aborter, job_id=job_id, reason="x")
    assert env.job(job_id).state is final


def test_edge_own_running_job_can_be_aborted_with_general_permission(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    assert env.core.cancel(env.alice, job_id=job_id, reason="間違えた").abort_pending


def test_edge_force_abort_requires_reason(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    with pytest.raises(ReasonRequired):
        env.core.cancel(env.alice, job_id=job_id)
    assert not env.job(job_id).abort_pending


def test_edge_second_abort_request_is_rejected(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    env.core.cancel(env.alice, job_id=job_id, reason="1")
    with pytest.raises(AbortAlreadyRequested):
        env.core.cancel(env.aborter, job_id=job_id, reason="2")
    job = env.job(job_id)
    assert job.cancellation is not None and job.cancellation.requested_by == "alice"


@pytest.mark.parametrize("outcome", [JobState.SUCCEEDED, JobState.FAILED])
def test_edge_finish_before_stop_confirmation_wins(env: Env, outcome: JobState) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    env.core.cancel(env.alice, job_id=job_id, reason="止めて")
    result = env.core.report_finished(env.runner1, runner_id="R1", job_id=job_id, outcome=outcome)
    assert result.state is outcome and result.superseded_abort
    job = env.job(job_id)
    assert job.cancellation is not None and job.cancellation.superseded_by is outcome
    complete = env.core.get_job_history(env.viewer, job_id=job_id)[-1]
    assert complete.operation is AuditOperation.COMPLETE
    assert complete.after == {"state": outcome.value, "superseded_abort": True}
    with pytest.raises(InvalidStateTransition):
        env.core.confirm_stopped(env.runner1, runner_id="R1", job_id=job_id)


def test_edge_on_behalf_job_can_be_cancelled_by_nominal_owner(env: Env) -> None:
    job_id = env.submit(env.service, on_behalf_of="alice").job_id
    env.core.cancel(env.alice, job_id=job_id)
    assert env.job(job_id).state is JobState.CANCELLED


def test_edge_cancel_records_reason_in_audit(env: Env) -> None:
    job_id = env.submit().job_id
    env.core.cancel(env.alice, job_id=job_id, reason="不要になった")
    record = env.core.get_job_history(env.viewer, job_id=job_id)[-1]
    assert record.operation is AuditOperation.CANCEL_QUEUED
    assert record.reason == "不要になった"
    assert record.before == {"state": "queued", "position": 1}


def test_edge_stop_confirmation_from_unassigned_runner_is_rejected(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    env.core.cancel(env.alice, job_id=job_id, reason="止めて")
    with pytest.raises(RunnerMismatch):
        env.core.confirm_stopped(env.runner2, runner_id="R2", job_id=job_id)
    assert env.job(job_id).abort_pending
    assert [r.denial_code for r in env.denied_records()] == ["runner_mismatch"]


def test_edge_unknown_job(env: Env) -> None:
    with pytest.raises(JobNotFound):
        env.core.cancel(env.alice, job_id="nope")
    with pytest.raises(JobNotFound):
        env.core.confirm_stopped(env.runner1, runner_id="R1", job_id="nope")
