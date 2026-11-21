"""US3: 空いた online のランナーに、条件を満たすジョブだけを割り当てる(spec US3-1〜US3-4、FR-013〜FR-015)。

US3-5(同時の要求)は test_concurrency_request_job.py。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.principal import Principal
from job_core.job.application import JobState
from job_core.job.domain.audit import AuditOperation
from job_core.runner.application import NotAssignedKind, RunnerState
from job_core.runner.domain.errors import RunnerIdentityMismatch

from .conftest import RunnerEnv, eq, requirement


def test_us3_1_skips_unmatched_front_job_and_assigns_matching_one_with_lease(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "a"})
    env.runner("r-b", {"k1": "b"})  # A を提出可能にするためのランナー
    job_a = env.submit(requirement(eq("k1", "b"))).job_id
    job_b = env.submit(requirement(eq("k1", "a"))).job_id
    assert env.queue_ids() == [job_a, job_b]

    start = env.core.clock.peek()
    result = env.request(runner)

    assert result.not_assigned_reason is None
    assignment = result.assignment
    assert assignment is not None
    assert assignment.job_id == job_b
    assert assignment.definition.job_type == "type-a"
    assert assignment.definition.payload == {"args": ["--run"]}
    assert start < assignment.lease_expires_at <= env.core.clock.peek() + timedelta(seconds=180)
    assert assignment.lease_expires_at - start >= timedelta(seconds=180) - timedelta(seconds=1)
    assert result.heartbeat_interval == timedelta(seconds=30)
    assert env.queue_ids() == [job_a]  # A は待機列に残る
    job = env.job(job_b)
    assert job.state is JobState.RUNNING
    assert job.assigned_runner_id == runner.runner_id
    assign_record = next(r for r in env.audit() if r.operation is AuditOperation.ASSIGN)
    assert assign_record.runner_id == runner.runner_id
    assert assign_record.after["lease_id"] == assignment.lease_id


def test_assigns_the_frontmost_matching_job(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "a"})
    first = env.submit(requirement(eq("k1", "a"))).job_id
    second = env.submit(requirement(eq("k1", "a"))).job_id
    result = env.request(runner)
    assert result.assignment is not None
    assert result.assignment.job_id == first
    assert env.queue_ids() == [second]


def test_us3_2_no_matching_job_assigns_nothing(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "a"})
    env.runner("r-b", {"k1": "b"})
    job = env.submit(requirement(eq("k1", "b"))).job_id
    result = env.request(runner)
    assert result.assignment is None
    assert result.not_assigned_reason is not None
    assert result.not_assigned_reason.kind is NotAssignedKind.NO_MATCHING_JOB
    assert env.queue_ids() == [job]
    assert [r for r in env.audit() if r.operation is AuditOperation.ASSIGN] == []


def test_us3_2_empty_queue(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    result = env.request(runner)
    assert result.assignment is None
    assert result.not_assigned_reason is not None
    assert result.not_assigned_reason.kind is NotAssignedKind.NO_MATCHING_JOB


def test_us3_3_runner_with_unfinished_job_is_not_assigned_another(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    first = env.submit().job_id
    second = env.submit().job_id
    assert env.request(runner).assignment is not None
    result = env.request(runner)
    assert result.assignment is None
    assert result.not_assigned_reason is not None
    assert result.not_assigned_reason.kind is NotAssignedKind.RUNNER_BUSY
    assert result.not_assigned_reason.job_id == first
    assert env.queue_ids() == [second]


@pytest.mark.parametrize("state", ["maintenance", "fault", "offline", "unregistered"])
def test_us3_4_runner_not_online_is_not_assigned(env: RunnerEnv, state: str) -> None:
    runner = env.runner("r-a", {}, register=state != "unregistered")
    other = env.runner("r-b", {})  # 提出を可能にする
    job = env.submit().job_id
    if state == "maintenance":
        env.core.set_maintenance(env.admin, runner_id=runner.runner_id)
        expected = RunnerState.MAINTENANCE
    elif state == "fault":
        env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
        expected = RunnerState.FAULT
    elif state == "offline":
        env.advance(91)
        expected = RunnerState.OFFLINE
    else:
        expected = RunnerState.OFFLINE
    result = env.request(runner)
    assert result.assignment is None
    assert result.not_assigned_reason is not None
    assert result.not_assigned_reason.kind is NotAssignedKind.NOT_ONLINE
    assert result.not_assigned_reason.state is expected
    assert env.queue_ids() == [job]
    assert other.runner_id != runner.runner_id


def test_offline_runner_must_send_heartbeat_first(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    env.advance(120)
    assert env.request(runner).assignment is None
    env.heartbeat(runner)
    result = env.request(runner)
    assert result.assignment is not None
    assert result.assignment.job_id == job


def test_request_job_in_lease_is_recorded_once(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.submit()
    assignment = env.request(runner).assignment
    assert assignment is not None
    with env.core.new_uow() as uow:
        lease = uow.leases.find_active_by_runner(runner.runner_id)  # type: ignore[arg-type]
        assert lease is not None
        assert lease.lease_id == assignment.lease_id
        assert lease.job_id == assignment.job_id
        assert lease.expires_at == assignment.lease_expires_at


def test_request_for_other_runner_is_rejected_and_audited(env: RunnerEnv) -> None:
    a = env.runner("r-a", {})
    b = env.runner("r-b", {})
    env.submit()
    with pytest.raises(RunnerIdentityMismatch):
        env.core.request_job(a.principal, runner_id=b.runner_id)
    assert env.queue_ids() != []
    denied = env.denied()
    assert denied[-1].denial_code == "runner_mismatch"
    assert denied[-1].runner_id == b.runner_id


def test_request_requires_both_report_and_execute_permissions(env: RunnerEnv) -> None:
    from job_core.job.domain.errors import PermissionDenied

    runner = env.runner("r-a", {})
    only_report = Principal.of(runner.runner_id, {"runner.report"})
    only_execute = Principal.of(runner.runner_id, {"job.execute"})
    for principal in (only_report, only_execute):
        with pytest.raises(PermissionDenied):
            env.core.request_job(principal, runner_id=runner.runner_id)


def test_request_updates_last_seen_but_not_registration(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    before = env.core.get_runner(env.viewer, runner_id=runner.runner_id)
    env.advance(20)
    env.request(runner)
    after = env.core.get_runner(env.viewer, runner_id=runner.runner_id)
    assert after.last_seen_at is not None and before.last_seen_at is not None
    assert after.last_seen_at > before.last_seen_at
    assert after.registered_at == before.registered_at


def test_finished_job_lease_is_ended_on_next_request(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    first = env.submit().job_id
    second = env.submit().job_id
    assert env.request(runner).assignment is not None
    env.finish(runner, first)
    result = env.request(runner)
    assert result.assignment is not None
    assert result.assignment.job_id == second
    with env.core.new_uow() as uow:
        active = uow.leases.list_active()
        assert [lease.job_id for lease in active] == [second]
