"""SweepRunners — 定期処理(research.md R8)。

offline になったランナーの記録(RUNNER_OFFLINE)と、期限切れのリースの記録(LEASE_EXPIRED、EXPIRED)、
終了したジョブのリースの終了(ENDED)を行う。冪等(2 回目は 0 件)。呼び出しの間隔(既定 15 秒)は 003 / 009 の責務。
ランナーごと・リースごとに UoW を分け、1 件の衝突が全体を止めないようにする(衝突した件は次の実行で処理される)。
割り当ての正しさは、この処理に依存しない(状態は時刻から導く。R6)。
"""

from __future__ import annotations

from functools import partial

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import ConcurrencyConflict
from job_core.runner.domain.runner import Connectivity
from job_core.shared.ids import JobId, RunnerId

from ..audit import append_connectivity_change, audited, make_runner_record
from ..authorization import authorize_sweep
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import SweepResult
from ..uow_support import run_in_runner_uow


class SweepRunners:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal) -> SweepResult:
        deps = self._deps
        audited(deps, principal, AuditOperation.RUNNER_SWEEP, None, lambda: authorize_sweep(principal))

        runner_ids = run_in_runner_uow(deps, lambda uow: [r.runner_id for r in uow.runners.list_active()])
        offline = 0
        for runner_id in runner_ids:
            try:
                if run_in_runner_uow(deps, partial(self._mark_offline, principal=principal, runner_id=runner_id)):
                    offline += 1
            except ConcurrencyConflict:
                continue

        job_ids = run_in_runner_uow(deps, lambda uow: [lease.job_id for lease in uow.leases.list_active()])
        expired = 0
        ended = 0
        for job_id in job_ids:
            try:
                outcome = run_in_runner_uow(deps, partial(self._settle, principal=principal, job_id=job_id))
            except ConcurrencyConflict:
                continue
            expired += outcome == "expired"
            ended += outcome == "ended"
        return SweepResult(offline, expired, ended)

    # ------------------------------------------------------------------ 内部

    def _mark_offline(self, uow: RunnerUnitOfWork, principal: Principal, runner_id: RunnerId) -> bool:
        deps = self._deps
        runner = uow.runners.get(runner_id)
        if runner is None or runner.is_deleted:
            return False
        now = deps.clock.now()
        if runner.connectivity_at(now, deps.timing) is not Connectivity.OFFLINE:
            return False
        if runner.recorded_connectivity is Connectivity.OFFLINE:
            return False
        changed = append_connectivity_change(deps, uow.audit, principal, runner, now=now)
        if changed:
            uow.runners.save(runner)
        return changed

    def _settle(self, uow: RunnerUnitOfWork, principal: Principal, job_id: JobId) -> str:
        """リース 1 件を整理する。'expired' / 'ended' / '' を返す。"""
        deps = self._deps
        lease = uow.leases.find_active_by_job(job_id)
        if lease is None:
            return ""
        now = deps.clock.now()
        job = uow.jobs.get(lease.job_id)
        if job is None or job.state.is_terminal or job.assigned_runner_id != lease.runner_id:
            lease.end()
            uow.leases.save(lease)
            return "ended"
        if lease.is_live_at(now):
            return ""
        before = {"expires_at": lease.expires_at.isoformat()}
        lease.expire(now)
        uow.leases.save(lease)
        uow.audit.append(
            make_runner_record(
                deps,
                principal,
                AuditOperation.LEASE_EXPIRED,
                lease.runner_id,
                job_id=lease.job_id,
                before=before,
                after={"status": lease.status.value},
            )
        )
        return "expired"
