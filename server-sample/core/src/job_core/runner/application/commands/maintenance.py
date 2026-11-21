"""SetMaintenance / ClearMaintenance — ランナーの無効化と解除(US6、FR-019)。

実行中のジョブ・リースは変えない(止めず、リースは生存通知で延長され続ける)。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.values import Reason
from job_core.shared.ids import RunnerId

from ..audit import audited, make_runner_record
from ..authorization import authorize_manage
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import RunnerView
from ..uow_support import run_in_runner_uow
from ._common import load_runner, view_of


class SetMaintenance:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, reason: str | None = None) -> RunnerView:
        deps = self._deps
        target = RunnerId(runner_id)
        audited(deps, principal, AuditOperation.RUNNER_MAINTENANCE_SET, target, lambda: authorize_manage(principal))
        why = Reason(reason) if reason is not None else None

        def operate(uow: RunnerUnitOfWork) -> RunnerView:
            runner = load_runner(uow, runner_id)
            now = deps.clock.now()
            before = runner.state_at(now, deps.timing).value
            runner.set_maintenance(principal.subject_id, now, why)
            uow.runners.save(runner)
            uow.audit.append(
                make_runner_record(
                    deps,
                    principal,
                    AuditOperation.RUNNER_MAINTENANCE_SET,
                    target,
                    before={"state": before},
                    after={"state": runner.state_at(now, deps.timing).value},
                    reason=why.value if why else None,
                )
            )
            return view_of(uow, deps, runner, now)

        return run_in_runner_uow(deps, operate)


class ClearMaintenance:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, reason: str | None = None) -> RunnerView:
        deps = self._deps
        target = RunnerId(runner_id)
        audited(deps, principal, AuditOperation.RUNNER_MAINTENANCE_CLEAR, target, lambda: authorize_manage(principal))
        why = Reason(reason) if reason is not None else None

        def operate(uow: RunnerUnitOfWork) -> RunnerView:
            runner = load_runner(uow, runner_id)
            now = deps.clock.now()
            before = runner.state_at(now, deps.timing).value
            runner.clear_maintenance()  # maintenance でなければ NotInMaintenance
            uow.runners.save(runner)
            uow.audit.append(
                make_runner_record(
                    deps,
                    principal,
                    AuditOperation.RUNNER_MAINTENANCE_CLEAR,
                    target,
                    before={"state": before},
                    after={"state": runner.state_at(now, deps.timing).value},
                    reason=why.value if why else None,
                )
            )
            return view_of(uow, deps, runner, now)

        return run_in_runner_uow(deps, operate)
