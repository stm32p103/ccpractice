"""DeleteRunner — ランナーの削除(US6-4、US6-5、FR-020、FR-021。contracts/application-api.md「DeleteRunner」)。

判定の順序: 存在 → 権限 → 未終了のジョブ(001 の find_unfinished_by_runner)。同じ UoW で確定する。
削除したランナーの識別子と名前は、監査記録(RUNNER_DELETE の before に名前)に残る。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.values import Reason
from job_core.runner.domain.errors import RunnerHasUnfinishedJob
from job_core.shared.ids import RunnerId

from ..audit import audited, make_runner_record
from ..authorization import authorize_manage
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..uow_support import run_in_runner_uow
from ._common import load_runner


class DeleteRunner:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, reason: str | None = None) -> None:
        deps = self._deps
        target = RunnerId(runner_id)
        why = Reason(reason).value if reason is not None else None

        def checked() -> None:
            run_in_runner_uow(deps, operate)

        def operate(uow: RunnerUnitOfWork) -> None:
            runner = load_runner(uow, runner_id)  # 存在
            authorize_manage(principal)  # 権限
            busy = uow.jobs.find_unfinished_by_runner(target)  # 未終了のジョブ
            if busy is not None:
                raise RunnerHasUnfinishedJob(busy.job_id)
            now = deps.clock.now()
            before = {"name": runner.name.value, "state": runner.state_at(now, deps.timing).value}
            runner.delete(now)
            uow.runners.save(runner)
            lease = uow.leases.find_active_by_runner(target)
            if lease is not None:  # ジョブは終了済み(未終了のジョブがないため)
                lease.end()
                uow.leases.save(lease)
            token = uow.tokens.find_valid_by_runner(target)
            if token is not None:
                token.revoke(now)
                uow.tokens.save(token)
            uow.audit.append(
                make_runner_record(
                    deps,
                    principal,
                    AuditOperation.RUNNER_DELETE,
                    target,
                    before=before,
                    after={"deleted_at": now.isoformat()},
                    reason=why,
                )
            )
            if token is not None:
                uow.audit.append(
                    make_runner_record(
                        deps,
                        principal,
                        AuditOperation.TOKEN_REVOKE,
                        target,
                        before={"token_id": token.token_id},
                        reason=why,
                    )
                )

        audited(deps, principal, AuditOperation.RUNNER_DELETE, target, checked)
