"""CancelJob — 取り消し・強制中断(US3、FR-014〜016。contracts/application-api.md「CancelJob」)。

権限はその時点の状態で判定する。同時に割り当てが成立した場合は、判定からのやり直しで実行中として判定し直す。
"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import InvalidStateTransition, JobNotFound, PermissionDenied
from job_core.job.domain.states import JobState
from job_core.job.domain.values import Reason
from job_core.shared.ids import JobId

from ..audit_support import make_record, record_denied
from ..authorization import authorize_cancel
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work


@dataclass(frozen=True)
class CancelResult:
    job_id: JobId
    state: JobState
    abort_pending: bool


class CancelJob:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, job_id: str, reason: str | None = None) -> CancelResult:
        deps = self._deps
        target = JobId(job_id)
        reason_value = Reason(reason) if reason is not None else None
        attempted_operation = [AuditOperation.CANCEL_QUEUED]

        def operate(uow: UnitOfWork) -> CancelResult:
            job = uow.jobs.get(target)
            if job is None:
                raise JobNotFound(target)
            attempted_operation[0] = (
                AuditOperation.CANCEL_QUEUED if job.state is JobState.QUEUED else AuditOperation.ABORT_REQUEST
            )
            authorize_cancel(principal, owner=job.submitter.owner, state=job.state)
            now = deps.clock.now()
            reason_text = reason_value.value if reason_value else None
            if job.state is JobState.QUEUED:
                queue = uow.queue.get()
                position = queue.remove(target)
                uow.queue.save(queue)
                job.cancel_queued(by=principal.subject_id, reason=reason_value, at=now, event_id=deps.ids.new_id())
                uow.jobs.save(job)
                uow.audit.append(
                    make_record(
                        deps,
                        principal,
                        AuditOperation.CANCEL_QUEUED,
                        target,
                        before={"state": JobState.QUEUED.value, "position": position},
                        after={"state": job.state.value},
                        reason=reason_text,
                    )
                )
            elif job.state is JobState.RUNNING:
                job.request_abort(by=principal.subject_id, reason=reason_value, at=now)
                uow.jobs.save(job)
                uow.audit.append(
                    make_record(
                        deps,
                        principal,
                        AuditOperation.ABORT_REQUEST,
                        target,
                        before={"state": JobState.RUNNING.value},
                        after={"state": job.state.value, "abort_requested": True},
                        reason=reason_text,
                    )
                )
            else:
                raise InvalidStateTransition(job.state.value, "cancel")
            return CancelResult(target, job.state, job.abort_pending)

        try:
            return run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries)
        except PermissionDenied as error:
            record_denied(
                deps,
                principal,
                attempted_operation[0],
                target,
                error,
                attempted={"reason_given": reason_value is not None},
            )
            raise
