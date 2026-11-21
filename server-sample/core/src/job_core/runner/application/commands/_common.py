"""runner のコマンドが共有する小さな部品(ランナーの読み込み、リースの扱い、応答の組み立て)。"""

from __future__ import annotations

from datetime import datetime

from job_core.job.application.ports import UnitOfWork
from job_core.runner.domain.errors import RunnerNotFound
from job_core.runner.domain.lease import Lease
from job_core.runner.domain.runner import Runner
from job_core.shared.ids import JobId, RunnerId

from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import HeartbeatResult, RunnerView, runner_view


def load_runner(uow: RunnerUnitOfWork, runner_id: str) -> Runner:
    """削除されていないランナーを読み込む。ない・削除済みなら RunnerNotFound。"""
    runner = uow.runners.get(RunnerId(runner_id))
    if runner is None or runner.is_deleted:
        raise RunnerNotFound(runner_id)
    return runner


def settle_lease(uow: RunnerUnitOfWork, runner_id: RunnerId) -> Lease | None:
    """ランナーの ACTIVE なリースを返す。

    ジョブが既に終了している(または別の割り当てになった)リースは、終了にして None を返す。

    ジョブの終了の報告(001)は変えないため、リースの終了は次の生存通知・割り当ての要求・定期処理で行う(research.md R7)。
    """
    lease = uow.leases.find_active_by_runner(runner_id)
    if lease is None:
        return None
    job = uow.jobs.get(lease.job_id)
    if job is None or job.state.is_terminal or job.assigned_runner_id != runner_id:
        lease.end()
        uow.leases.save(lease)
        return None
    return lease


def live_lease_expiry(uow: RunnerUnitOfWork, runner_id: RunnerId, now: datetime) -> datetime | None:
    """有効なリース(ACTIVE かつ期限前)があれば、その期限。"""
    lease = uow.leases.find_active_by_runner(runner_id)
    if lease is not None and lease.is_live_at(now):
        return lease.expires_at
    return None


def heartbeat_result(
    uow: RunnerUnitOfWork, deps: RunnerDependencies, runner: Runner, now: datetime, *, lease_expires_at: datetime | None
) -> HeartbeatResult:
    return HeartbeatResult(
        state=runner.state_at(now, deps.timing),
        lease_expires_at=lease_expires_at,
        heartbeat_interval=deps.timing.heartbeat_interval,
    )


def view_of(uow: UnitOfWork, deps: RunnerDependencies, runner: Runner, now: datetime) -> RunnerView:
    job = uow.jobs.find_unfinished_by_runner(runner.runner_id)
    running: JobId | None = job.job_id if job is not None else None
    return runner_view(runner, now=now, policy=deps.timing, running_job_id=running)
