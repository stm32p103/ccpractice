"""ReportFinished — 終了の報告(contracts/application-api.md「ReportFinished」)。

判定の順序: 入力の形式 → 存在 → 権限 → 割り当て先の一致 → 状態。
割り当て先でないランナーからの報告は RunnerMismatch とし、監査ログに DENIED を残す(research.md R6)。
"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import JobNotFound, ValidationFailed
from job_core.job.domain.states import JobState
from job_core.job.domain.values import ResultSummary
from job_core.shared.ids import JobId, RunnerId

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_execute
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work


@dataclass(frozen=True)
class FinishResult:
    job_id: JobId
    state: JobState
    superseded_abort: bool


class ReportFinished:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(
        self,
        principal: Principal,
        *,
        runner_id: str,
        job_id: str,
        outcome: JobState | str,
        result_summary: str | None = None,
    ) -> FinishResult:
        deps = self._deps
        try:
            outcome_state = JobState(outcome)
        except ValueError as exc:
            raise ValidationFailed("outcome", "succeeded または failed でなければならない") from exc
        if outcome_state not in (JobState.SUCCEEDED, JobState.FAILED):
            raise ValidationFailed("outcome", "succeeded または failed でなければならない")
        summary = ResultSummary(result_summary) if result_summary is not None else None
        runner = RunnerId(runner_id)
        target = JobId(job_id)

        def operate(uow: UnitOfWork) -> FinishResult:
            job = uow.jobs.get(target)
            if job is None:
                raise JobNotFound(target)
            authorize_execute(principal)
            had_abort_request = job.abort_pending
            job.finish(
                runner_id=runner,
                outcome=outcome_state,
                summary=summary,
                at=deps.clock.now(),
                event_id=deps.ids.new_id(),
            )
            uow.jobs.save(job)
            after: dict[str, object] = {"state": job.state.value}
            if had_abort_request:
                after["superseded_abort"] = True
            uow.audit.append(
                make_record(
                    deps,
                    principal,
                    AuditOperation.COMPLETE,
                    job.job_id,
                    before={"state": JobState.RUNNING.value},
                    after=after,
                )
            )
            return FinishResult(job.job_id, job.state, had_abort_request)

        return audited_denials(
            deps,
            principal,
            AuditOperation.COMPLETE,
            target,
            lambda: run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries),
            attempted={"runner_id": runner, "outcome": outcome_state.value},
        )
