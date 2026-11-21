"""US2 — 位置を指定した追加とスケジュール変更(spec US2-1〜US2-7 とエッジケース)。"""

from __future__ import annotations

import itertools

import pytest

from job_core.job.application import (
    AnchorNotQueued,
    AuditOperation,
    JobNotFound,
    JobState,
    PermissionDenied,
    Placement,
    SelfAnchor,
    TargetNotQueued,
)

from .conftest import Env


@pytest.fixture
def abc(env: Env) -> list[str]:
    return [str(j) for j in env.submit_many(3)]


def test_us2_1_insert_before_head_without_stopping_running_job(env: Env) -> None:
    running = env.submit().job_id
    env.run(running)
    a, b, c = env.submit_many(3)
    x = env.submit(env.scheduler, placement=Placement.before(a)).job_id
    assert env.queue_ids() == [x, a, b, c]
    assert env.job(running).state is JobState.RUNNING  # 実行中のジョブは止まらない(FR-013)
    env.finish(running)
    assert env.assign() == x


def test_us2_2_insert_after(env: Env, abc: list[str]) -> None:
    a, b, c = abc
    x = env.submit(env.scheduler, placement=Placement.after(a)).job_id
    assert env.queue_ids() == [a, x, b, c]


def test_us2_3_move_before(env: Env, abc: list[str]) -> None:
    a, b, c = abc
    result = env.core.reschedule(env.scheduler, job_id=c, placement=Placement.before(a))
    assert (result.position_before, result.position_after) == (3, 1)
    assert env.queue_ids() == [c, a, b]
    assert env.assign() == c


def test_us2_4_move_after_keeps_relative_order_of_others(env: Env, abc: list[str]) -> None:
    a, b, c = abc
    env.core.reschedule(env.scheduler, job_id=a, placement=Placement.after(b))
    assert env.queue_ids() == [b, a, c]


def test_us2_5_moving_others_job_is_audited_with_positions(env: Env) -> None:
    mine = env.submit(env.alice).job_id
    other = env.submit(env.bob).job_id
    env.core.reschedule(env.scheduler, job_id=other, placement=Placement.before(mine))
    record = env.core.get_job_history(env.alice, job_id=other)[-1]
    assert record.operation is AuditOperation.RESCHEDULE
    assert record.actor == "sched"
    assert record.before == {"position": 2}
    assert record.after == {"position": 1, "anchor": mine, "side": "before"}


def test_us2_6_submit_permission_alone_cannot_place_or_move(env: Env, abc: list[str]) -> None:
    a, b, _ = abc
    with pytest.raises(PermissionDenied) as placed:
        env.submit(env.alice, placement=Placement.before(a))
    assert placed.value.required == ("queue.schedule",)
    with pytest.raises(PermissionDenied):
        env.core.reschedule(env.alice, job_id=b, placement=Placement.before(a))
    assert env.queue_ids() == abc
    operations = [r.operation for r in env.denied_records()]
    assert operations == [AuditOperation.SUBMIT_PLACED, AuditOperation.RESCHEDULE]


def test_us2_7_only_queued_jobs_can_be_target_or_anchor(env: Env) -> None:
    running = env.submit().job_id
    env.run(running)
    finished = env.submit(requirement={"os": "y"}).job_id
    env.run(finished, "R2")
    env.finish(finished, runner_id="R2")
    queued = env.submit().job_id
    for not_queued in (running, finished):
        with pytest.raises(TargetNotQueued):
            env.core.reschedule(env.scheduler, job_id=not_queued, placement=Placement.before(queued))
        with pytest.raises(AnchorNotQueued):
            env.core.reschedule(env.scheduler, job_id=queued, placement=Placement.before(not_queued))
        with pytest.raises(AnchorNotQueued):
            env.submit(env.scheduler, placement=Placement.after(not_queued))
    assert env.queue_ids() == [queued]


def test_edge_placed_submit_with_non_queued_anchor_does_not_fall_back_to_tail(env: Env) -> None:
    a = env.submit().job_id
    env.run(a)
    with pytest.raises(AnchorNotQueued):
        env.submit(env.scheduler, placement=Placement.before(a))
    assert env.queue_ids() == []
    with env.core.new_uow() as uow:
        assert len(uow.jobs.list_by_states([JobState.QUEUED], None, None).items) == 0


def test_edge_placed_submit_into_empty_queue_is_rejected(env: Env) -> None:
    with pytest.raises(AnchorNotQueued):
        env.submit(env.scheduler, placement=Placement.before("anything"))


def test_edge_moving_job_relative_to_itself_is_rejected(env: Env, abc: list[str]) -> None:
    with pytest.raises(SelfAnchor):
        env.core.reschedule(env.scheduler, job_id=abc[0], placement=Placement.after(abc[0]))


def test_edge_move_that_keeps_position_succeeds_without_change(env: Env, abc: list[str]) -> None:
    a, b, _ = abc
    result = env.core.reschedule(env.scheduler, job_id=a, placement=Placement.before(b))
    assert (result.position_before, result.position_after) == (1, 1)
    assert env.queue_ids() == abc


def test_edge_consecutive_moves_last_one_wins_and_both_are_audited(env: Env, abc: list[str]) -> None:
    a, b, c = abc
    other_scheduler = env.scheduler.__class__.of("sched2", env.scheduler.permissions)
    env.core.reschedule(env.scheduler, job_id=c, placement=Placement.before(a))
    env.core.reschedule(other_scheduler, job_id=c, placement=Placement.after(b))
    assert env.queue_ids() == [a, b, c]
    moves = [r for r in env.core.get_job_history(env.viewer, job_id=c) if r.operation is AuditOperation.RESCHEDULE]
    assert [r.actor for r in moves] == ["sched", "sched2"]


def test_edge_one_operation_per_job_reflects_agreed_order(env: Env) -> None:
    jobs = env.submit_many(5)
    agreed = [jobs[3], jobs[0], jobs[4], jobs[1], jobs[2]]
    operations = 0
    # 相談の結果を、先頭から順に「前のジョブの後ろ」へ移すことで反映する(1 件につき 1 回。SC-004)
    env.core.reschedule(env.scheduler, job_id=agreed[0], placement=Placement.before(env.queue_ids()[0]))
    operations += 1
    for previous, current in itertools.pairwise(agreed):
        env.core.reschedule(env.scheduler, job_id=current, placement=Placement.after(previous))
        operations += 1
    assert env.queue_ids() == agreed
    assert operations <= len(agreed)


def test_edge_move_unknown_job(env: Env, abc: list[str]) -> None:
    with pytest.raises(JobNotFound):
        env.core.reschedule(env.scheduler, job_id="nope", placement=Placement.before(abc[0]))


def test_edge_no_dedicated_head_or_tail_operation(env: Env, abc: list[str]) -> None:
    a, _, c = abc
    env.core.reschedule(env.scheduler, job_id=c, placement=Placement.before(a))  # 先頭へ = 先頭のジョブの前
    env.core.reschedule(env.scheduler, job_id=c, placement=Placement.after(env.queue_ids()[-1]))  # 末尾へ
    assert env.queue_ids() == abc
    assert not hasattr(env.core, "move_to_head")
