"""US5: 機材の異常を申告し、割り当てを自動で止める(spec US5-1〜US5-5、FR-011、FR-012、SC-006)。"""

from __future__ import annotations

import pytest

from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import PermissionDenied, ValidationFailed
from job_core.runner.application import NotAssignedKind, RunnerState

from .conftest import RunnerEnv


def ops(env: RunnerEnv, runner_id: str) -> list[AuditOperation]:
    return [r.operation for r in env.audit() if r.runner_id == runner_id]


def test_us5_1_fault_report_stops_assignment_and_is_visible_to_everyone(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    result = env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    assert result.state is RunnerState.FAULT
    refusal = env.request(runner)
    assert refusal.assignment is None
    assert refusal.not_assigned_reason is not None
    assert refusal.not_assigned_reason.kind is NotAssignedKind.NOT_ONLINE
    assert refusal.not_assigned_reason.state is RunnerState.FAULT
    assert env.queue_ids() == [job]
    view = env.core.get_runner(env.viewer, runner_id=runner.runner_id)  # 全員が確認できる
    assert view.state is RunnerState.FAULT
    assert view.fault_description == "e1"
    record = next(r for r in env.audit() if r.operation is AuditOperation.FAULT_REPORT)
    assert record.after == {"fault": "e1"}
    assert record.actor == runner.runner_id


def test_us5_2_recovery_resumes_assignment(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    result = env.core.report_recovered(runner.principal, runner_id=runner.runner_id)
    assert result.state is RunnerState.ONLINE
    assigned = env.request(runner).assignment
    assert assigned is not None and assigned.job_id == job
    assert AuditOperation.FAULT_RECOVERED in ops(env, runner.runner_id)


def test_us5_3_running_job_is_not_stopped_and_lease_keeps_extending(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    assert env.request(runner).assignment is not None
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    assert env.job(job).state.value == "running"
    env.advance(100)
    assert env.heartbeat(runner).lease_expires_at is not None
    assert env.state(runner.runner_id) == "fault"


def test_us5_4_fault_is_not_cleared_by_going_offline_and_back(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    env.advance(300)
    env.core.sweep_runners(env.sweeper)
    result = env.heartbeat(runner)
    assert result.state is RunnerState.FAULT
    assert env.state(runner.runner_id) == "fault"


def test_us5_5_manual_clear_by_manage_permission_resumes_assignment(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    with pytest.raises(PermissionDenied):
        env.core.clear_fault(env.viewer, runner_id=runner.runner_id)
    view = env.core.clear_fault(env.admin, runner_id=runner.runner_id, reason="点検済み")
    assert view.state is RunnerState.ONLINE
    assigned = env.request(runner).assignment
    assert assigned is not None and assigned.job_id == job
    clear = next(r for r in env.audit(outcome="succeeded") if r.operation is AuditOperation.FAULT_CLEAR)
    assert clear.actor == "admin"
    assert clear.reason == "点検済み"
    assert clear.before == {"fault": "e1"}


def test_manual_clear_of_stale_runner_leaves_it_offline(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    env.advance(300)
    view = env.core.clear_fault(env.admin, runner_id=runner.runner_id)
    assert view.state is RunnerState.OFFLINE


def test_edge_repeated_fault_report_only_updates_description(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e2")
    assert env.core.get_runner(env.viewer, runner_id=runner.runner_id).fault_description == "e2"
    assert env.state(runner.runner_id) == "fault"
    reports = [r for r in env.audit() if r.operation is AuditOperation.FAULT_REPORT]
    assert [r.before["fault"] for r in reports] == [None, "e1"]
    assert [r.after["fault"] for r in reports] == ["e1", "e2"]


def test_edge_recovery_without_fault_changes_nothing_and_is_not_audited(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    count = len(env.audit())
    result = env.core.report_recovered(runner.principal, runner_id=runner.runner_id)
    assert result.state is RunnerState.ONLINE
    assert len(env.audit()) == count
    env.core.clear_fault(env.admin, runner_id=runner.runner_id)  # 管理側の解除も、異常がなければ記録しない
    assert len(env.audit()) == count


@pytest.mark.parametrize("bad", ["", "   ", "a" * 201, "line1\nline2", "tab\there"])
def test_description_limits(env: RunnerEnv, bad: str) -> None:
    runner = env.runner("r-a", {})
    with pytest.raises(ValidationFailed):
        env.core.report_fault(runner.principal, runner_id=runner.runner_id, description=bad)
    assert env.state(runner.runner_id) == "online"


def test_fault_reports_are_recorded_while_in_maintenance_and_reflected_after(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.set_maintenance(env.admin, runner_id=runner.runner_id)
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    assert env.state(runner.runner_id) == "maintenance"
    env.core.clear_maintenance(env.admin, runner_id=runner.runner_id)
    assert env.state(runner.runner_id) == "fault"


def test_no_assignment_after_fault_report(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    for _ in range(5):
        env.submit()
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    for _ in range(5):
        env.advance(5)
        assert env.request(runner).assignment is None
    with env.core.new_uow() as uow:
        assert uow.leases.list_active() == []


def test_fault_report_requires_own_token(env: RunnerEnv) -> None:
    from job_core.runner.application import RunnerIdentityMismatch

    a = env.runner("r-a", {})
    b = env.runner("r-b", {})
    with pytest.raises(RunnerIdentityMismatch):
        env.core.report_fault(a.principal, runner_id=b.runner_id, description="e1")
    assert env.state(b.runner_id) == "online"
