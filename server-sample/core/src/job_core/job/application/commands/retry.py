"""RetryJob — やり直し(US4、FR-017〜020。contracts/application-api.md「RetryJob」)。

元のジョブの定義をそのまま引き継いだ新しいジョブを作る。元のジョブは変更しない。
新しいジョブの提出者(名義・実際に提出した主体)は、やり直しを行った主体とする。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.definition import Submitter
from job_core.job.domain.errors import InvalidStateTransition, JobNotFound
from job_core.job.domain.values import Placement
from job_core.shared.ids import JobId

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_retry
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work
from ._admission import admit, placement_fields
from .submit import SubmitResult


class RetryJob:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, job_id: str, placement: Placement | None = None) -> SubmitResult:
        deps = self._deps
        original_id = JobId(job_id)

        def operate(uow: UnitOfWork) -> SubmitResult:
            original = uow.jobs.get(original_id)
            if original is None:
                raise JobNotFound(original_id)  # 保持期間を過ぎて削除されたジョブを含む
            authorize_retry(principal, placed=placement is not None)
            if not original.state.is_terminal:
                raise InvalidStateTransition(original.state.value, "retry")
            job, position = admit(
                uow,
                deps,
                definition=original.definition,
                submitter=Submitter(owner=principal.subject_id, submitted_by=principal.subject_id),
                placement=placement,
                retry_of=original.job_id,
            )
            uow.audit.append(
                make_record(
                    deps,
                    principal,
                    AuditOperation.RETRY,
                    job.job_id,
                    after={
                        "state": job.state.value,
                        "position": position,
                        "retry_of": original.job_id,
                        **placement_fields(placement),
                    },
                )
            )
            return SubmitResult(job.job_id, position)

        return audited_denials(
            deps,
            principal,
            AuditOperation.RETRY,
            original_id,
            lambda: run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries),
            attempted={"placed": placement is not None, **placement_fields(placement)},
        )
