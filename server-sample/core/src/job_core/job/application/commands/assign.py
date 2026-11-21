"""AssignNextJob — 割り当て(US1、FR-009〜010。contracts/application-api.md「AssignNextJob」、research.md R6)。"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import RunnerBusy
from job_core.job.domain.states import JobState
from job_core.shared.ids import JobId, RunnerId

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_execute
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work


@dataclass(frozen=True)
class AssignResult:
    job_id: JobId | None


class AssignNextJob:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str) -> AssignResult:
        deps = self._deps
        runner = RunnerId(runner_id)
        audited_denials(
            deps,
            principal,
            AuditOperation.ASSIGN,
            None,
            lambda: authorize_execute(principal),
            attempted={"runner_id": runner},
        )

        def operate(uow: UnitOfWork) -> AssignResult:
            busy = uow.jobs.find_unfinished_by_runner(runner)
            if busy is not None:
                raise RunnerBusy(busy.job_id)  # 1 台に同時に 2 件を割り当てない(FR-010)
            queue = uow.queue.get()
            requirements = {
                job.job_id: job.definition.requirement
                for job in uow.jobs.list_by_states([JobState.QUEUED], None, None).items
            }
            chosen = queue.first_matching(
                lambda job_id: (
                    job_id in requirements and deps.eligibility.runner_satisfies(runner, requirements[job_id])
                )
            )
            if chosen is None:
                return AssignResult(None)
            job = uow.jobs.get(chosen)
            if job is None:  # pragma: no cover - 待機列とジョブの不一致(不変条件 2 の違反)
                raise RuntimeError(f"待機列のジョブ {chosen} が存在しない")
            position = queue.remove(chosen)
            uow.queue.save(queue)
            job.assign(runner, deps.clock.now())
            uow.jobs.save(job)
            uow.audit.append(
                make_record(
                    deps,
                    principal,
                    AuditOperation.ASSIGN,
                    job.job_id,
                    before={"state": JobState.QUEUED.value, "position": position},
                    after={"state": job.state.value, "runner_id": runner},
                )
            )
            return AssignResult(job.job_id)

        return run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries)
