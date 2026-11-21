"""移動と割り当ての競合(spec Edge Cases「スケジュール変更と割り当てが同時に起きる」)。"""

from __future__ import annotations

import pytest

from job_core.job.application import AnchorNotQueued, JobState, Placement, TargetNotQueued

from .conftest import Env


def test_concurrency_target_assigned_first_rejects_move(env: Env) -> None:
    a, b = env.submit_many(2)
    env.core.store.inject_before_next_commit(lambda: env.assign())  # a が割り当てられる
    with pytest.raises(TargetNotQueued):
        env.core.reschedule(env.scheduler, job_id=a, placement=Placement.after(b))
    assert env.queue_ids() == [b]
    assert env.job(a).state is JobState.RUNNING
    env.assert_consistent()


def test_concurrency_anchor_assigned_first_rejects_move(env: Env) -> None:
    a, b = env.submit_many(2)
    env.core.store.inject_before_next_commit(lambda: env.assign())  # 基準の a が割り当てられる
    with pytest.raises(AnchorNotQueued):
        env.core.reschedule(env.scheduler, job_id=b, placement=Placement.before(a))
    assert env.queue_ids() == [b]
    env.assert_consistent()


def test_concurrency_move_unrelated_to_assignment_still_succeeds(env: Env) -> None:
    _a, b, c = env.submit_many(3)
    env.core.store.inject_before_next_commit(lambda: env.assign())  # a が割り当てられる
    env.core.reschedule(env.scheduler, job_id=c, placement=Placement.before(b))
    assert env.queue_ids() == [c, b]
    env.assert_consistent()
