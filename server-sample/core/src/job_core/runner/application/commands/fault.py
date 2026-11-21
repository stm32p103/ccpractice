"""異常の申告と回復、手動の解除(US5、FR-011、FR-012。research.md R13)。

- ReportFault / ReportRecovered: ランナー経由の申告。最終応答時刻も更新する(生存通知を兼ねる)。
  異常のときの再申告は説明だけを更新する。異常でないときの回復の申告は、何も変えず監査にも残さない(冪等)。
- ClearFault: ランナー管理の権限による手動の解除(ツールが回復を申告できない場合)。
- 実行中のジョブは、システムからは止めない。リースも生存通知で延長され続ける。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.values import Reason
from job_core.runner.domain.values import FaultDescription
from job_core.shared.ids import RunnerId

from ..audit import append_connectivity_change, audited, make_runner_record
from ..authorization import authorize_manage, authorize_report, require_self
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import HeartbeatResult, RunnerView
from ..uow_support import run_in_runner_uow
from ._common import heartbeat_result, live_lease_expiry, load_runner, view_of


class ReportFault:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, description: str) -> HeartbeatResult:
        deps = self._deps
        target = RunnerId(runner_id)

        def checked() -> HeartbeatResult:
            authorize_report(principal)
            require_self(principal, target)
            text = FaultDescription(description)
            return run_in_runner_uow(deps, lambda uow: operate(uow, text))

        def operate(uow: RunnerUnitOfWork, text: FaultDescription) -> HeartbeatResult:
            runner = load_runner(uow, runner_id)
            now = deps.clock.now()
            before = runner.fault.description.value if runner.fault else None
            runner.seen(now)
            runner.report_fault(text, now)
            uow.runners.save(runner)
            append_connectivity_change(deps, uow.audit, principal, runner, now=now)
            uow.audit.append(
                make_runner_record(
                    deps,
                    principal,
                    AuditOperation.FAULT_REPORT,
                    target,
                    before={"fault": before},
                    after={"fault": text.value},
                )
            )
            return heartbeat_result(uow, deps, runner, now, lease_expires_at=live_lease_expiry(uow, target, now))

        return audited(deps, principal, AuditOperation.FAULT_REPORT, target, checked)


class ReportRecovered:
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
            before = runner.fault.description.value if runner.fault else None
            runner.seen(now)
            recovered = runner.report_recovered()
            uow.runners.save(runner)
            append_connectivity_change(deps, uow.audit, principal, runner, now=now)
            if recovered:
                uow.audit.append(
                    make_runner_record(
                        deps,
                        principal,
                        AuditOperation.FAULT_RECOVERED,
                        target,
                        before={"fault": before},
                        after={"fault": None},
                    )
                )
            return heartbeat_result(uow, deps, runner, now, lease_expires_at=live_lease_expiry(uow, target, now))

        return audited(deps, principal, AuditOperation.FAULT_RECOVERED, target, checked)


class ClearFault:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, reason: str | None = None) -> RunnerView:
        deps = self._deps
        target = RunnerId(runner_id)
        audited(deps, principal, AuditOperation.FAULT_CLEAR, target, lambda: authorize_manage(principal))
        why = Reason(reason).value if reason is not None else None

        def operate(uow: RunnerUnitOfWork) -> RunnerView:
            runner = load_runner(uow, runner_id)
            now = deps.clock.now()
            before = runner.fault.description.value if runner.fault else None
            if runner.clear_fault():  # 異常がなければ記録せず、変化なしで成功する
                uow.runners.save(runner)
                uow.audit.append(
                    make_runner_record(
                        deps,
                        principal,
                        AuditOperation.FAULT_CLEAR,
                        target,
                        before={"fault": before},
                        after={"fault": None},
                        reason=why,
                    )
                )
            return view_of(uow, deps, runner, now)

        return run_in_runner_uow(deps, operate)
