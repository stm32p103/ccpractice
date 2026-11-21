"""ConfirmStopped — 停止の確認(contracts/application-api.md「ConfirmStopped」)。

判定の順序と runner_id の前提は ReportFinished と同じ。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import JobNotFound
from job_core.job.domain.states import JobState
from job_core.shared.ids import JobId, RunnerId

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_execute
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work
from .report_finished import FinishResult


class ConfirmStopped:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, job_id: str) -> FinishResult:
        deps = self._deps
        runner = RunnerId(runner_id)
        target = JobId(job_id)

        def operate(uow: UnitOfWork) -> FinishResult:
            job = uow.jobs.get(target)
            if job is None:
                raise JobNotFound(target)
            authorize_execute(principal)
            job.confirm_stopped(runner_id=runner, at=deps.clock.now(), event_id=deps.ids.new_id())
            uow.jobs.save(job)
            uow.audit.append(
                make_record(
                    deps,
                    principal,
                    AuditOperation.ABORT_CONFIRM,
                    job.job_id,
                    before={"state": JobState.RUNNING.value},
                    after={"state": job.state.value},
                )
            )
            return FinishResult(job.job_id, job.state, False)

        return audited_denials(
            deps,
            principal,
            AuditOperation.ABORT_CONFIRM,
            target,
            lambda: run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries),
            attempted={"runner_id": runner},
        )
