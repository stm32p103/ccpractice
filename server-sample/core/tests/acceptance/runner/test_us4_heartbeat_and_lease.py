"""US4: 生存通知でランナーの状態とリースを保つ(spec US4-1〜US4-5、FR-010、FR-015〜FR-018、SC-004、SC-005)。"""

from __future__ import annotations

import inspect
from datetime import timedelta

import pytest

from job_core.job.domain.audit import AuditOperation
from job_core.runner.application import (
    Heartbeat,
    LeaseStatus,
    RunnerNotFound,
    RunnerNotRegistered,
    RunnerState,
)

from .conftest import RunnerEnv

LEASE = timedelta(seconds=180)


def started_job(env: RunnerEnv, name: str = "r-a") -> tuple:  # type: ignore[type-arg]
    runner = env.runner(name, {})
    job_id = env.submit().job_id
    assignment = env.request(runner).assignment
    assert assignment is not None
    return runner, job_id, assignment


def test_us4_1_heartbeat_brings_offline_runner_online(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.advance(120)
    assert env.state(runner.runner_id) == "offline"
    before = env.core.get_runner(env.viewer, runner_id=runner.runner_id).last_seen_at
    result = env.heartbeat(runner)
    assert result.state is RunnerState.ONLINE
    assert result.lease_expires_at is None
    assert env.state(runner.runner_id) == "online"
    after = env.core.get_runner(env.viewer, runner_id=runner.runner_id).last_seen_at
    assert before is not None and after is not None and after > before
    onlines = [r for r in env.audit() if r.operation is AuditOperation.RUNNER_ONLINE]
    # 定期処理が動いていなければ、記録上は online のまま(登録の分だけ)。状態の導出と割り当ては記録に依らない
    assert len(onlines) == 1


def test_us4_1_online_transition_is_audited_only_on_change(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.sweep_runners(env.sweeper)  # 登録で online と記録済み
    for _ in range(5):
        env.advance(10)
        env.heartbeat(runner)  # 状態が変わらない通知は記録しない
    onlines = [r for r in env.audit() if r.operation is AuditOperation.RUNNER_ONLINE]
    assert len(onlines) == 1
    env.advance(200)
    env.core.sweep_runners(env.sweeper)
    env.heartbeat(runner)
    connectivity = (AuditOperation.RUNNER_ONLINE, AuditOperation.RUNNER_OFFLINE)
    ops = [r.operation for r in env.audit() if r.operation in connectivity]
    assert ops == [AuditOperation.RUNNER_ONLINE, AuditOperation.RUNNER_OFFLINE, AuditOperation.RUNNER_ONLINE]
    assert not any(r.operation is AuditOperation.RUNNER_HEARTBEAT for r in env.audit())  # 生存通知そのものは記録しない


def test_us4_2_heartbeat_before_expiry_extends_lease_from_receive_time(env: RunnerEnv) -> None:
    runner, _, assignment = started_job(env)
    env.advance(100)
    result = env.heartbeat(runner)
    now = env.core.clock.peek()
    assert result.lease_expires_at is not None
    assert result.lease_expires_at > assignment.lease_expires_at
    assert now - timedelta(seconds=1) < result.lease_expires_at - LEASE <= now  # 受信時刻 + リースの長さ


def test_duplicate_heartbeats_do_not_change_the_result_beyond_receive_time(env: RunnerEnv) -> None:
    runner, _, _ = started_job(env)
    env.advance(30)
    first = env.heartbeat(runner).lease_expires_at
    second = env.heartbeat(runner).lease_expires_at  # 重複(ほぼ同時)
    assert first is not None and second is not None
    assert timedelta(0) <= second - first < timedelta(seconds=1)


def test_us4_3_online_runner_goes_offline_after_threshold_and_is_audited(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.advance(89)
    assert env.state(runner.runner_id) == "online"
    env.advance(2)
    assert env.state(runner.runner_id) == "offline"
    result = env.core.sweep_runners(env.sweeper)
    assert result.runners_marked_offline == 1
    offline = [r for r in env.audit() if r.operation is AuditOperation.RUNNER_OFFLINE]
    assert len(offline) == 1
    assert offline[0].actor == "sweeper"
    assert offline[0].runner_id == runner.runner_id
    assert offline[0].before["connectivity"] == "online"
    assert offline[0].after["connectivity"] == "offline"


def test_us4_4_lease_expires_without_extension_and_is_not_revived(env: RunnerEnv) -> None:
    runner, job_id, assignment = started_job(env)
    env.advance(181)
    result = env.heartbeat(runner)  # 期限後の通知は延長しない
    assert result.lease_expires_at is None
    sweep = env.core.sweep_runners(env.sweeper)
    assert sweep.leases_expired == 1
    expired = [r for r in env.audit() if r.operation is AuditOperation.LEASE_EXPIRED]
    assert len(expired) == 1
    assert expired[0].job_id == job_id
    assert expired[0].runner_id == runner.runner_id
    assert expired[0].after == {"status": "expired"}
    with env.core.new_uow() as uow:
        assert uow.leases.list_active() == []
        assert uow.leases.find_active_by_job(job_id) is None  # type: ignore[arg-type]
    # 以後、そのリースの延長は受け付けない
    assert env.heartbeat(runner).lease_expires_at is None
    # 004 FR-024: リース切れのジョブは、待機列へ戻さず、失敗として確定する(再実行しない)。ランナーは空く
    job = env.job(job_id)
    assert job.state.value == "failed"
    assert job.result_detail is not None and job.result_detail.failure_reason == "lease_expired"
    with pytest.raises(Exception, match="failed から finish"):
        env.finish(runner, job_id)  # 確定後の報告は拒否される
    assert env.queue_ids() == []  # 待機列へ戻っていない
    env.submit()
    again = env.request(runner)
    assert again.assignment is not None and again.assignment.lease_id != assignment.lease_id


def test_us4_5_maintenance_runner_updates_last_seen_but_stays_maintenance(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.set_maintenance(env.admin, runner_id=runner.runner_id)
    before = env.core.get_runner(env.viewer, runner_id=runner.runner_id).last_seen_at
    env.advance(30)
    result = env.heartbeat(runner)
    after = env.core.get_runner(env.viewer, runner_id=runner.runner_id).last_seen_at
    assert result.state is RunnerState.MAINTENANCE
    assert before is not None and after is not None and after > before
    assert env.state(runner.runner_id) == "maintenance"


def test_edge_server_time_only_heartbeat_has_no_time_parameter() -> None:
    parameters = inspect.signature(Heartbeat.__call__).parameters
    assert set(parameters) == {"self", "principal", "runner_id"}


def test_sc4_stale_runner_is_not_assigned_even_without_sweep(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.submit()
    env.advance(90 + 30)  # offline と判定する時間 + 30 秒(定期処理は動いていない)
    result = env.request(runner)
    assert result.assignment is None
    assert result.not_assigned_reason is not None
    assert result.not_assigned_reason.state is RunnerState.OFFLINE


def test_sc5_steady_heartbeats_never_let_the_lease_expire(env: RunnerEnv) -> None:
    runner, job_id, _ = started_job(env)
    for _ in range(1000):  # 長時間のジョブを模す(30 秒間隔で約 8 時間)
        env.advance(30)
        assert env.heartbeat(runner).lease_expires_at is not None
    sweep = env.core.sweep_runners(env.sweeper)
    assert sweep.leases_expired == 0
    assert sweep.runners_marked_offline == 0
    with env.core.new_uow() as uow:
        lease = uow.leases.find_active_by_job(job_id)  # type: ignore[arg-type]
        assert lease is not None and lease.status is LeaseStatus.ACTIVE
    assert env.state(runner.runner_id) == "online"


def test_heartbeat_on_unregistered_runner(env: RunnerEnv) -> None:
    runner = env.runner("r-a", register=False)
    with pytest.raises(RunnerNotRegistered):
        env.heartbeat(runner)


def test_heartbeat_on_deleted_runner(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.delete_runner(env.admin, runner_id=runner.runner_id)
    with pytest.raises(RunnerNotFound):
        env.heartbeat(runner)


def test_heartbeat_ends_lease_of_finished_job(env: RunnerEnv) -> None:
    runner, job_id, _ = started_job(env)
    env.finish(runner, job_id)
    result = env.heartbeat(runner)
    assert result.lease_expires_at is None
    with env.core.new_uow() as uow:
        assert uow.leases.list_active() == []
