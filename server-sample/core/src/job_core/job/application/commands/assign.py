"""AssignNextJob — 割り当て(US1、FR-009〜010。contracts/application-api.md「AssignNextJob」、research.md R6)。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import RunnerBusy
from job_core.job.domain.states import JobState
from job_core.job.domain.values import RunnerRequirement
from job_core.shared.ids import JobId, RunnerId

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_execute
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work


@dataclass(frozen=True)
class AssignResult:
    job_id: JobId | None


def assign_next_in(
    uow: UnitOfWork,
    deps: CoreDependencies,
    principal: Principal,
    runner_id: RunnerId,
    satisfies: Callable[[RunnerRequirement], bool],
    *,
    lease_id: str | None = None,
) -> AssignResult:
    """割り当ての本体。呼び出し側が開いた UoW の中で、待機列の走査 → 取り出し → 実行中へ → 監査 ASSIGN を行う。

    satisfies は、そのランナーが要件を満たすかの述語(002 の RequestJob は、ランナーの能力での照合を渡す)。
    lease_id は、同じ UoW で作るリースの識別子(あれば監査記録に残す)。確定(commit)は呼び出し側が行う。
    """
    busy = uow.jobs.find_unfinished_by_runner(runner_id)
    if busy is not None:
        raise RunnerBusy(busy.job_id)  # 1 台に同時に 2 件を割り当てない(FR-010)
    queue = uow.queue.get()
    requirements = {
        job.job_id: job.definition.requirement for job in uow.jobs.list_by_states([JobState.QUEUED], None, None).items
    }
    chosen = queue.first_matching(lambda job_id: job_id in requirements and satisfies(requirements[job_id]))
    if chosen is None:
        return AssignResult(None)
    job = uow.jobs.get(chosen)
    if job is None:  # pragma: no cover - 待機列とジョブの不一致(不変条件 2 の違反)
        raise RuntimeError(f"待機列のジョブ {chosen} が存在しない")
    position = queue.remove(chosen)
    uow.queue.save(queue)
    job.assign(runner_id, deps.clock.now())
    uow.jobs.save(job)
    after: dict[str, object] = {"state": job.state.value, "runner_id": runner_id}
    if lease_id is not None:
        after["lease_id"] = lease_id
    uow.audit.append(
        make_record(
            deps,
            principal,
            AuditOperation.ASSIGN,
            job.job_id,
            before={"state": JobState.QUEUED.value, "position": position},
            after=after,
            runner_id=runner_id,
        )
    )
    return AssignResult(job.job_id)


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
            return assign_next_in(
                uow, deps, principal, runner, lambda requirement: deps.eligibility.runner_satisfies(runner, requirement)
            )

        return run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries)
