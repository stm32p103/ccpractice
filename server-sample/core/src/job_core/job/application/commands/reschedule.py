"""RescheduleJob — スケジュール変更(US2、FR-011〜013。contracts/application-api.md「RescheduleJob」)。

実行中のジョブには触れない(待機列は待機中のジョブだけを持つ。FR-013)。
"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import JobNotFound, SelfAnchor, TargetNotQueued
from job_core.job.domain.values import Placement
from job_core.shared.ids import JobId

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_reschedule
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work
from ._admission import placement_fields


@dataclass(frozen=True)
class RescheduleResult:
    job_id: JobId
    position_before: int
    position_after: int


class RescheduleJob:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, job_id: str, placement: Placement) -> RescheduleResult:
        deps = self._deps
        target = JobId(job_id)
        if target == placement.anchor:
            raise SelfAnchor()

        def operate(uow: UnitOfWork) -> RescheduleResult:
            job = uow.jobs.get(target)
            if job is None:
                raise JobNotFound(target)
            authorize_reschedule(principal)
            queue = uow.queue.get()
            if target not in queue:
                raise TargetNotQueued(target, job.state.value)
            before, after = queue.move(target, placement)
            uow.queue.save(queue)
            uow.audit.append(
                make_record(
                    deps,
                    principal,
                    AuditOperation.RESCHEDULE,
                    target,
                    before={"position": before},
                    after={"position": after, **placement_fields(placement)},
                )
            )
            return RescheduleResult(target, before, after)

        return audited_denials(
            deps,
            principal,
            AuditOperation.RESCHEDULE,
            target,
            lambda: run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries),
            attempted=placement_fields(placement),
        )
