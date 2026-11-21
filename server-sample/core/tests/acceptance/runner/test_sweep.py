"""SweepRunners の冪等性と記録(research.md R8。US4-3、US4-4)。"""

from __future__ import annotations

import pytest

from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import PermissionDenied

from .conftest import RunnerEnv


def test_sweep_records_offline_once_and_is_idempotent(env: RunnerEnv) -> None:
    env.runner("r-a", {})
    env.runner("r-b", {})
    env.advance(100)
    first = env.core.sweep_runners(env.sweeper)
    second = env.core.sweep_runners(env.sweeper)
    assert (first.runners_marked_offline, first.leases_expired, first.leases_ended) == (2, 0, 0)
    assert (second.runners_marked_offline, second.leases_expired, second.leases_ended) == (0, 0, 0)
    assert len([r for r in env.audit() if r.operation is AuditOperation.RUNNER_OFFLINE]) == 2


def test_sweep_does_not_touch_never_registered_or_online_runners(env: RunnerEnv) -> None:
    env.runner("r-new", register=False)
    live = env.runner("r-live", {})
    env.advance(60)
    env.heartbeat(live)
    result = env.core.sweep_runners(env.sweeper)
    assert result.runners_marked_offline == 0


def test_sweep_expires_overdue_lease_and_ends_finished_job_lease(env: RunnerEnv) -> None:
    a = env.runner("r-a", {})
    b = env.runner("r-b", {})
    job_a = env.submit().job_id
    job_b = env.submit().job_id
    assert env.request(a).assignment is not None
    assert env.request(b).assignment is not None
    env.finish(b, job_b)  # b のジョブは終了済み。リースは次の整理で ENDED
    env.advance(181)
    result = env.core.sweep_runners(env.sweeper)
    assert (result.leases_expired, result.leases_ended) == (1, 1)
    expired = [r for r in env.audit() if r.operation is AuditOperation.LEASE_EXPIRED]
    assert [r.job_id for r in expired] == [job_a]
    again = env.core.sweep_runners(env.sweeper)
    assert (again.runners_marked_offline, again.leases_expired, again.leases_ended) == (0, 0, 0)


def test_sweep_requires_sweep_permission(env: RunnerEnv) -> None:
    for principal in (env.admin, env.nobody, env.auditor):
        with pytest.raises(PermissionDenied) as err:
            env.core.sweep_runners(principal)
        assert err.value.required == ("runner.sweep",)
    assert len(env.denied()) == 3


def test_sweep_skips_deleted_runners(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.delete_runner(env.admin, runner_id=runner.runner_id)
    env.advance(500)
    assert env.core.sweep_runners(env.sweeper).runners_marked_offline == 0
