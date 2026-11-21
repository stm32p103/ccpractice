"""取り消しと割り当ての競合(spec Edge Cases「中断の操作と割り当てが同時に起きる」)。"""

from __future__ import annotations

import pytest

from job_core.job.application import JobState, PermissionDenied

from .conftest import Env


def test_concurrency_cancel_first_means_not_assigned(env: Env) -> None:
    a, b = env.submit_many(2)
    env.core.cancel(env.alice, job_id=a)
    assert env.assign() == b
    env.assert_consistent()


def test_concurrency_assignment_first_turns_own_cancel_into_abort_request(env: Env) -> None:
    a = env.submit().job_id
    env.core.store.inject_before_next_commit(lambda: env.assign())
    result = env.core.cancel(env.alice, job_id=a, reason="止めて")
    assert result.state is JobState.RUNNING and result.abort_pending
    env.assert_consistent()


def test_concurrency_assignment_first_denies_cancel_only_principal(env: Env) -> None:
    a = env.submit(env.bob).job_id
    env.core.store.inject_before_next_commit(lambda: env.assign())
    with pytest.raises(PermissionDenied) as denial:
        env.core.cancel(env.canceller, job_id=a, reason="x")
    assert denial.value.required == ("job.force_abort",)
    job = env.job(a)
    assert job.state is JobState.RUNNING and not job.abort_pending
    env.assert_consistent()
