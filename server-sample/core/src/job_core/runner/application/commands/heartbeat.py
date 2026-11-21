"""Heartbeat — 生存通知(US4、FR-016。research.md R7)。

最終応答時刻を更新し、有効なリース(期限前で、ジョブが実行中で、割り当て先がこのランナー)だけを
受信時刻から lease_duration だけ延長する。期限を過ぎたリースは延長せず、lease_expires_at は None を返す。
ジョブが終了しているリースは ENDED にする。リースの延長は監査に残さない(状態の変化だけを記録する)。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.shared.ids import RunnerId

from ..audit import append_connectivity_change, audited
from ..authorization import authorize_report, require_self
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import HeartbeatResult
from ..uow_support import run_in_runner_uow
from ._common import heartbeat_result, load_runner, settle_lease


class Heartbeat:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str) -> HeartbeatResult:
        deps = self._deps
        target = RunnerId(runner_id)

        def checked() -> HeartbeatResult:
            authorize_report(principal)
            require_self(principal, target)
            return run_in_runner_uow(deps, operate)

        def operate(uow: RunnerUnitOfWork) -> HeartbeatResult:
            runner = load_runner(uow, runner_id)
            now = deps.clock.now()
            runner.touch(now)  # 未登録なら RunnerNotRegistered
            uow.runners.save(runner)
            append_connectivity_change(deps, uow.audit, principal, runner, now=now)
            expires = None
            lease = settle_lease(uow, target)
            if lease is not None and lease.is_live_at(now):
                lease.extend(now, deps.timing)
                uow.leases.save(lease)
                expires = lease.expires_at
            return heartbeat_result(uow, deps, runner, now, lease_expires_at=expires)

        return audited(deps, principal, AuditOperation.RUNNER_HEARTBEAT, target, checked)
