"""Edge Cases の残りの受け入れテスト(spec「Edge Cases」)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.job.application import JobState, NoEligibleRunner
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.values import RunnerRequirement
from job_core.shared.ids import RunnerId

from .conftest import RunnerEnv, eq, requirement


def test_empty_requirement_is_satisfied_by_every_registered_runner(env: RunnerEnv) -> None:
    a = env.runner("r-a", {})
    b = env.runner("r-b", {"k1": "x"})
    first = env.submit(requirement()).job_id
    second = env.submit(requirement()).job_id
    assert env.request(a).assignment is not None
    assert env.request(b).assignment is not None
    assert {env.job(first).assigned_runner_id, env.job(second).assigned_runner_id} == {a.runner_id, b.runner_id}


def test_empty_declaration_runner_satisfies_only_empty_requirement(env: RunnerEnv) -> None:
    env.runner("r-a", {})
    env.submit(requirement())
    with pytest.raises(NoEligibleRunner):
        env.submit(requirement(eq("k1", "x")))


def test_reregistration_that_removes_the_only_eligible_runner_keeps_queued_jobs(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "a"})
    job = env.submit(requirement(eq("k1", "a"))).job_id
    env.core.register_runner(runner.principal, runner_id=runner.runner_id, capabilities={"k1": "b"})
    assert env.queue_ids() == [job]  # 自動では取り消さない
    assert env.job(job).state is JobState.QUEUED
    assert env.request(runner).assignment is None  # 割り当てなし(待機列に残り続ける)
    # 提出時の判定だけが、新しい提出を拒否する
    with pytest.raises(NoEligibleRunner):
        env.submit(requirement(eq("k1", "a")))


def test_reregistration_does_not_stop_a_running_job(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "a"})
    job = env.submit(requirement(eq("k1", "a"))).job_id
    assert env.request(runner).assignment is not None
    env.core.register_runner(runner.principal, runner_id=runner.runner_id, capabilities={"k1": "other"})
    assert env.job(job).state is JobState.RUNNING  # 能力の変更を理由に止めない
    assert env.heartbeat(runner).lease_expires_at is not None


def test_reregistration_with_live_lease_is_accepted_and_audited(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.submit()
    assignment = env.request(runner).assignment
    assert assignment is not None
    result = env.core.register_runner(runner.principal, runner_id=runner.runner_id, capabilities={"k1": "a"})
    assert result.lease_expires_at == assignment.lease_expires_at  # 登録は延長しない
    registers = [r for r in env.audit() if r.operation is AuditOperation.RUNNER_REGISTER]
    assert [r.after["had_live_lease"] for r in registers] == [False, True]


def test_reregistration_after_lease_expired_reports_no_live_lease(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.submit()
    assert env.request(runner).assignment is not None
    env.advance(300)
    env.core.register_runner(runner.principal, runner_id=runner.runner_id, capabilities={})
    registers = [r for r in env.audit() if r.operation is AuditOperation.RUNNER_REGISTER]
    assert registers[-1].after["had_live_lease"] is False


def test_never_registered_runner_is_offline_and_satisfies_only_empty_requirement(env: RunnerEnv) -> None:
    runner = env.runner("r-new", register=False)
    assert env.state(runner.runner_id) == "offline"
    env.advance(1000)
    assert env.state(runner.runner_id) == "offline"
    assert env.core.runner_eligibility.runner_satisfies(RunnerId(runner.runner_id), RunnerRequirement.of(requirement()))


def test_deleted_name_can_be_reused_with_a_different_id_and_old_name_stays_in_audit(env: RunnerEnv) -> None:
    old = env.runner("same", {})
    env.core.delete_runner(env.admin, runner_id=old.runner_id)
    new = env.runner("same", {})
    assert new.runner_id != old.runner_id
    old_history = env.core.get_runner_history(env.viewer, runner_id=old.runner_id)
    assert any(r.operation is AuditOperation.RUNNER_DELETE and r.before["name"] == "same" for r in old_history)
    new_history = env.core.get_runner_history(env.viewer, runner_id=new.runner_id)
    assert all(r.runner_id == new.runner_id for r in new_history)


def test_capability_type_mismatch_on_capability_side_just_does_not_match(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "not-a-number"})
    env.runner("r-b", {"k1": "5"})  # 提出を可能にする
    job = env.submit({"all": [{"key": "k1", "op": "num_ge", "value": "1"}]}).job_id
    assert env.request(runner).assignment is None  # エラーにならず、満たさない
    assert env.queue_ids() == [job]


def test_state_and_lease_decisions_use_server_time_only(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.submit()
    assignment = env.request(runner).assignment
    assert assignment is not None
    env.advance(60)
    result = env.heartbeat(runner)
    assert result.lease_expires_at is not None
    assert result.lease_expires_at - env.core.clock.peek() <= timedelta(seconds=180)
