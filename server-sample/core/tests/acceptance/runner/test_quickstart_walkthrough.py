"""quickstart.md §3 のシナリオ 1〜10 の通しの実行と、SC-011 の最短の経路(build_core() を使用)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.permission import Permission
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application import AuditOperation, NoEligibleRunner
from job_core.runner.application import (
    InvalidDeclaration,
    NotAssignedKind,
    RunnerAuthenticationFailed,
    RunnerHasUnfinishedJob,
    RunnerIdentityMismatch,
    RunnerState,
)
from job_testing.core_fakes import build_core

from .conftest import contains, eq, requirement


def test_quickstart_scenarios_1_to_10() -> None:
    core = build_core(use_runner_management=True)
    admin = Principal.of("admin", {Permission.RUNNER_MANAGE, Permission.GENERAL})
    auditor = Principal.of("auditor", {Permission.AUDIT_READ_ALL})
    sweeper = Principal.of("sweeper", {Permission.RUNNER_SWEEP}, PrincipalKind.SYSTEM)
    alice = Principal.of("alice", {Permission.JOB_SUBMIT, Permission.GENERAL})

    def submit(req: dict[str, object]) -> str:
        return core.submit(alice, job_type="t", requirement=req, payload={"a": 1}, timeout=timedelta(minutes=5)).job_id

    # 1. 作成と登録
    core.replace_allowlist(admin, entries={"k1": "single", "set1": "set"})
    created = core.create_runner(admin, name="r-a")
    runner = core.authenticate_runner(created.token.value)
    core.register_runner(runner, runner_id=created.runner_id, capabilities={"k1": "a", "set1": ["x", "y"]})
    listed = core.list_runners(admin)
    assert (listed[0].state, listed[0].capabilities) == (RunnerState.ONLINE, {"k1": "a", "set1": ["x", "y"]})
    assert created.token.value not in repr(listed)

    # 2. 許可リスト外のキー
    with pytest.raises(InvalidDeclaration):
        core.register_runner(runner, runner_id=created.runner_id, capabilities={"k9": "z"})
    assert core.get_runner(admin, runner_id=created.runner_id).capabilities == {"k1": "a", "set1": ["x", "y"]}

    # 3. 判定(offline でも提出できる)
    core.clock.advance(timedelta(minutes=2))
    assert core.get_runner(admin, runner_id=created.runner_id).state is RunnerState.OFFLINE
    submit(requirement(contains("set1", "y")))

    # 4. 条件を満たすジョブだけ
    other = core.create_runner(admin, name="r-b")
    other_principal = core.authenticate_runner(other.token.value)
    core.register_runner(other_principal, runner_id=other.runner_id, capabilities={"k1": "b"})
    job_a = submit(requirement(eq("k1", "b")))
    job_b = submit(requirement(eq("k1", "a")))
    core.heartbeat(runner, runner_id=created.runner_id)
    # 待機列は [set1 のジョブ, A, B]。r-a が条件を満たす最前のジョブは set1 のジョブ
    first = core.request_job(runner, runner_id=created.runner_id).assignment
    assert first is not None
    assert first.lease_expires_at

    # 5. 生存通知とリース
    core.clock.advance(timedelta(seconds=30))
    extended = core.heartbeat(runner, runner_id=created.runner_id).lease_expires_at
    assert extended is not None and extended > first.lease_expires_at
    core.clock.advance(timedelta(minutes=3))
    assert core.heartbeat(runner, runner_id=created.runner_id).lease_expires_at is None
    core.sweep_runners(sweeper)
    assert [r.operation for r in core.get_audit_log(auditor, limit=1000).items].count(AuditOperation.LEASE_EXPIRED) == 1

    # 6. 異常(別のランナー r-b で確認する)
    core.heartbeat(other_principal, runner_id=other.runner_id)
    core.report_fault(other_principal, runner_id=other.runner_id, description="e1")
    refused = core.request_job(other_principal, runner_id=other.runner_id).not_assigned_reason
    assert refused is not None and (refused.kind, refused.state) == (NotAssignedKind.NOT_ONLINE, RunnerState.FAULT)
    core.report_recovered(other_principal, runner_id=other.runner_id)
    assigned = core.request_job(other_principal, runner_id=other.runner_id).assignment
    assert assigned is not None and assigned.job_id == job_a

    # 7. maintenance(実行中のジョブは止まらず、リースは延びる)
    core.set_maintenance(admin, runner_id=other.runner_id)
    assert core.heartbeat(other_principal, runner_id=other.runner_id).lease_expires_at is not None
    assert core.get_job(alice, job_id=job_a).summary.state.value == "running"

    # 8. 削除の拒否
    with pytest.raises(RunnerHasUnfinishedJob):
        core.delete_runner(admin, runner_id=other.runner_id)

    # 9. トークンの失効と再発行
    reissued = core.reissue_token(admin, runner_id=created.runner_id)
    with pytest.raises(RunnerAuthenticationFailed):
        core.authenticate_runner(created.token.value)
    core.authenticate_runner(reissued.value)

    # 10. なりすまし
    with pytest.raises(RunnerIdentityMismatch):
        core.heartbeat(other_principal, runner_id=created.runner_id)
    assert core.get_audit_log(auditor, outcome="denied", limit=1000).items[-1].denial_code == "runner_mismatch"
    assert job_b


def test_sc011_shortest_path_create_once_then_register_and_receive_a_job() -> None:
    """権限を持つ利用者の作成 1 回と、受け取ったトークンでの登録だけで、online になり割り当てを受けられる。"""
    core = build_core(use_runner_management=True)
    admin = Principal.of("admin", {Permission.RUNNER_MANAGE, Permission.GENERAL})
    alice = Principal.of("alice", {Permission.JOB_SUBMIT, Permission.GENERAL})
    core.replace_allowlist(admin, entries={"k1": "single"})

    created = core.create_runner(admin, name="r-a")  # 作成(トークンの受け取り)1 回
    principal = core.authenticate_runner(created.token.value)  # PC に設定したトークンで
    registered = core.register_runner(principal, runner_id=created.runner_id, capabilities={"k1": "a"})
    assert registered.state is RunnerState.ONLINE
    core.submit(
        alice,
        job_type="t",
        requirement=requirement(eq("k1", "a")),
        payload={},
        timeout=timedelta(minutes=1),
    )
    assert core.request_job(principal, runner_id=created.runner_id).assignment is not None


def test_a_job_without_any_eligible_runner_is_rejected_before_runners_exist() -> None:
    core = build_core(use_runner_management=True)
    alice = Principal.of("alice", {Permission.JOB_SUBMIT, Permission.GENERAL})
    with pytest.raises(NoEligibleRunner):
        core.submit(alice, job_type="t", requirement=requirement(), payload={}, timeout=timedelta(minutes=1))
