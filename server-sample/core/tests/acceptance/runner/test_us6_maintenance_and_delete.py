"""US6: ランナーを無効化(maintenance)・削除する(spec US6-1〜US6-5、FR-019〜FR-021)。"""

from __future__ import annotations

import pytest

from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import PermissionDenied
from job_core.runner.application import (
    AlreadyInMaintenance,
    NotAssignedKind,
    NotInMaintenance,
    RunnerAuthenticationFailed,
    RunnerHasUnfinishedJob,
    RunnerNotFound,
    RunnerState,
)
from job_core.shared.ids import RunnerId

from .conftest import RunnerEnv


def test_us6_1_maintenance_stops_assignment_and_is_audited_with_reason(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    view = env.core.set_maintenance(env.admin, runner_id=runner.runner_id, reason="保守")
    assert view.state is RunnerState.MAINTENANCE
    assert view.maintenance_reason == "保守"
    refusal = env.request(runner)
    assert refusal.not_assigned_reason is not None
    assert refusal.not_assigned_reason.state is RunnerState.MAINTENANCE
    assert env.queue_ids() == [job]
    record = next(r for r in env.audit() if r.operation is AuditOperation.RUNNER_MAINTENANCE_SET)
    assert record.reason == "保守"
    assert record.before == {"state": "online"}
    assert record.after == {"state": "maintenance"}
    with pytest.raises(AlreadyInMaintenance):
        env.core.set_maintenance(env.admin, runner_id=runner.runner_id)


def test_us6_2_running_job_is_not_stopped_and_lease_keeps_extending(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    assert env.request(runner).assignment is not None
    env.core.set_maintenance(env.admin, runner_id=runner.runner_id)
    assert env.job(job).state.value == "running"
    env.advance(100)
    assert env.heartbeat(runner).lease_expires_at is not None


@pytest.mark.parametrize(
    ("fault", "stale", "expected"),
    [
        (True, False, RunnerState.FAULT),
        (False, False, RunnerState.ONLINE),
        (False, True, RunnerState.OFFLINE),
        (True, True, RunnerState.FAULT),
    ],
)
def test_us6_3_clearing_maintenance_returns_to_state_by_fault_and_liveness(
    env: RunnerEnv, fault: bool, stale: bool, expected: RunnerState
) -> None:
    runner = env.runner("r-a", {})
    env.core.set_maintenance(env.admin, runner_id=runner.runner_id)
    if fault:
        env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    if stale:
        env.advance(300)
    view = env.core.clear_maintenance(env.admin, runner_id=runner.runner_id, reason="終了")
    assert view.state is expected
    with pytest.raises(NotInMaintenance):
        env.core.clear_maintenance(env.admin, runner_id=runner.runner_id)


def test_us6_4_delete_idle_runner_invalidates_token_and_leaves_eligibility_and_assignment(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "a"})
    env.core.delete_runner(env.admin, runner_id=runner.runner_id, reason="撤去")
    assert env.core.list_runners(env.viewer) == ()
    with pytest.raises(RunnerNotFound):
        env.core.get_runner(env.viewer, runner_id=runner.runner_id)
    with pytest.raises(RunnerAuthenticationFailed):
        env.core.authenticate_runner(runner.token)
    with pytest.raises(RunnerNotFound):
        env.request(runner)
    assert env.core.runner_eligibility.runner_satisfies(RunnerId(runner.runner_id), _req()) is False
    ops = [r.operation for r in env.audit() if r.runner_id == runner.runner_id]
    assert AuditOperation.RUNNER_DELETE in ops
    assert AuditOperation.TOKEN_REVOKE in ops


def _req():  # type: ignore[no-untyped-def]
    from job_core.job.domain.values import RunnerRequirement

    return RunnerRequirement.of({"all": []})


def test_us6_5_delete_runner_with_unfinished_job_is_rejected(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    assert env.request(runner).assignment is not None
    with pytest.raises(RunnerHasUnfinishedJob) as err:
        env.core.delete_runner(env.admin, runner_id=runner.runner_id)
    assert err.value.job_id == job
    assert env.state(runner.runner_id) == "online"
    env.core.authenticate_runner(runner.token)  # トークンも有効なまま


def test_delete_after_job_finished_succeeds(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    assert env.request(runner).assignment is not None
    env.finish(runner, job)
    env.core.delete_runner(env.admin, runner_id=runner.runner_id)
    with env.core.new_uow() as uow:
        assert uow.leases.list_active() == []


def test_fr021_deleted_runner_id_and_name_remain_traceable_in_audit_log(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.delete_runner(env.admin, runner_id=runner.runner_id)
    records = env.audit(runner_id=runner.runner_id)
    delete = next(r for r in records if r.operation is AuditOperation.RUNNER_DELETE)
    assert delete.runner_id == runner.runner_id
    assert delete.before["name"] == "r-a"
    create = next(r for r in records if r.operation is AuditOperation.RUNNER_CREATE)
    assert create.after == {"name": "r-a"}


def test_delete_judgement_order_is_existence_then_permission_then_unfinished_job(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.submit()
    assert env.request(runner).assignment is not None
    with pytest.raises(RunnerNotFound):
        env.core.delete_runner(env.nobody, runner_id="no-such-runner")
    with pytest.raises(PermissionDenied):
        env.core.delete_runner(env.nobody, runner_id=runner.runner_id)
    with pytest.raises(RunnerHasUnfinishedJob):
        env.core.delete_runner(env.admin, runner_id=runner.runner_id)
    assert any(d.operation is AuditOperation.RUNNER_DELETE for d in env.denied())


def test_maintenance_and_delete_require_manage_permission(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    for principal in (env.nobody, env.viewer, env.auditor, runner.principal):
        with pytest.raises(PermissionDenied):
            env.core.set_maintenance(principal, runner_id=runner.runner_id)
        with pytest.raises(PermissionDenied):
            env.core.clear_maintenance(principal, runner_id=runner.runner_id)
        with pytest.raises(PermissionDenied):
            env.core.delete_runner(principal, runner_id=runner.runner_id)
    assert env.state(runner.runner_id) == "online"


def test_maintenance_on_unknown_runner(env: RunnerEnv) -> None:
    with pytest.raises(RunnerNotFound):
        env.core.set_maintenance(env.admin, runner_id="nope")


def test_assignment_refused_reason_kind_is_not_online(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.set_maintenance(env.admin, runner_id=runner.runner_id)
    env.submit()
    reason = env.request(runner).not_assigned_reason
    assert reason is not None and reason.kind is NotAssignedKind.NOT_ONLINE
