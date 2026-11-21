"""RegisterRunner — 起動時の登録と能力の申告(US1-3〜5、FR-002〜FR-004、FR-006)。

許可リストの検査 → Runner.register → 接続の記録 → 監査 RUNNER_REGISTER(had_live_lease を含む)。
許可リストに合わない申告は、登録ごと拒否する。能力・最終応答時刻は変えず、DENIED(invalid_declaration)を残す。
"""

from __future__ import annotations

from typing import Any

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.shared.ids import RunnerId

from ..audit import append_connectivity_change, audited, make_runner_record
from ..authorization import authorize_report, require_self
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import HeartbeatResult
from ..uow_support import run_in_runner_uow
from ._common import heartbeat_result, live_lease_expiry, load_runner


class RegisterRunner:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, capabilities: Any) -> HeartbeatResult:
        deps = self._deps
        target = RunnerId(runner_id)

        def checked() -> HeartbeatResult:
            authorize_report(principal)
            require_self(principal, target)
            return run_in_runner_uow(deps, operate)

        def operate(uow: RunnerUnitOfWork) -> HeartbeatResult:
            runner = load_runner(uow, runner_id)
            declared = uow.allowlist.get().validate(capabilities)  # 合わなければ InvalidDeclaration
            now = deps.clock.now()
            before = {"capabilities": runner.capabilities.to_json(), "state": runner.state_at(now, deps.timing).value}
            had_live_lease = live_lease_expiry(uow, target, now) is not None
            runner.register(declared, now)
            uow.runners.save(runner)
            uow.audit.append(
                make_runner_record(
                    deps,
                    principal,
                    AuditOperation.RUNNER_REGISTER,
                    target,
                    before=before,
                    after={
                        "capabilities": runner.capabilities.to_json(),
                        "state": runner.state_at(now, deps.timing).value,
                        "had_live_lease": had_live_lease,
                    },
                )
            )
            append_connectivity_change(deps, uow.audit, principal, runner, now=now)  # 登録の結果としての online
            return heartbeat_result(uow, deps, runner, now, lease_expires_at=live_lease_expiry(uow, target, now))

        return audited(deps, principal, AuditOperation.RUNNER_REGISTER, target, checked)
