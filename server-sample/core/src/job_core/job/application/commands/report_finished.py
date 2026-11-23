"""ReportFinished — 終了の報告(contracts/application-api.md「ReportFinished」)。

判定の順序: 入力の形式 → 存在 → 権限 → 割り当て先の一致 → 状態。
割り当て先でないランナーからの報告は RunnerMismatch とし、監査ログに DENIED を残す(research.md R6)。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import JobNotFound, ValidationFailed
from job_core.job.domain.output import (
    MAX_ARTIFACTS,
    MAX_RUNNER_SUMMARY_CHARS,
    JobArtifactRef,
    ResultCounters,
    ResultDetail,
)
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
        exit_code: int | None = None,
        failure_reason: str | None = None,
        artifacts: Sequence[JobArtifactRef] = (),
        counters: ResultCounters | None = None,
    ) -> FinishResult:
        deps = self._deps
        try:
            outcome_state = JobState(outcome)
        except ValueError as exc:
            raise ValidationFailed("outcome", "succeeded または failed でなければならない") from exc
        if outcome_state not in (JobState.SUCCEEDED, JobState.FAILED):
            raise ValidationFailed("outcome", "succeeded または failed でなければならない")
        if result_summary is not None and len(result_summary) > MAX_RUNNER_SUMMARY_CHARS:
            raise ValidationFailed("result_summary", "200 文字以内でなければならない")
        if len(artifacts) > MAX_ARTIFACTS:
            raise ValidationFailed("artifacts", "上限を超えている")
        if outcome_state is JobState.SUCCEEDED and failure_reason is not None:
            raise ValidationFailed("failure_reason", "成功では指定できない")
        summary = ResultSummary(result_summary) if result_summary is not None else None
        detail = ResultDetail(exit_code, failure_reason, counters or ResultCounters())
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
                detail=detail,
            )
            uow.jobs.save(job)
            after: dict[str, object] = {"state": job.state.value}
            if detail.failure_reason is not None:
                after["failure_reason"] = detail.failure_reason
            if detail.exit_code is not None:
                after["exit_code"] = detail.exit_code
            if detail.counters != ResultCounters():
                after["counters"] = {
                    "path_rejections": detail.counters.path_rejections,
                    "masked_lines": detail.counters.masked_lines,
                    "log_truncated": detail.counters.log_truncated,
                }
            if artifacts:
                after["artifact_count"] = len(artifacts)
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

        result = audited_denials(
            deps,
            principal,
            AuditOperation.COMPLETE,
            target,
            lambda: run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries),
            attempted={"runner_id": runner, "outcome": outcome_state.value},
        )
        if artifacts and deps.outputs is not None:
            deps.outputs.save_artifacts(target, artifacts)
        return result
