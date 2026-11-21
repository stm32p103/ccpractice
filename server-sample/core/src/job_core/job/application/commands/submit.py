"""SubmitJob — 提出(US1、US2、FR-001〜007。contracts/application-api.md「SubmitJob」)。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.definition import JobDefinition, Submitter
from job_core.job.domain.errors import ValidationFailed
from job_core.job.domain.values import JsonValue, Placement
from job_core.shared.ids import JobId, SubjectId, is_valid_id

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_submit
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work
from ._admission import admit, placement_fields


@dataclass(frozen=True)
class SubmitResult:
    job_id: JobId
    position: int


class SubmitJob:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(
        self,
        principal: Principal,
        *,
        job_type: str | None,
        requirement: JsonValue,
        payload: JsonValue,
        timeout: timedelta | None,
        source: str | None = None,
        revision: str | None = None,
        on_behalf_of: str | None = None,
        placement: Placement | None = None,
    ) -> SubmitResult:
        deps = self._deps
        if on_behalf_of is not None and not is_valid_id(on_behalf_of):
            raise ValidationFailed("on_behalf_of", "空でない識別子でなければならない")
        owner = SubjectId(on_behalf_of) if on_behalf_of is not None else principal.subject_id
        behalf = owner if owner != principal.subject_id else None
        operation = AuditOperation.SUBMIT if placement is None else AuditOperation.SUBMIT_PLACED

        # ① 権限 → ② 定義の検証 → ③ ランナーの判定 → ④ 基準のジョブ → ⑤ 重複
        audited_denials(
            deps,
            principal,
            operation,
            None,
            lambda: authorize_submit(principal, owner=owner, placed=placement is not None),
            attempted={"placed": placement is not None, **placement_fields(placement)},
            on_behalf_of=behalf,
        )
        definition = JobDefinition.create(
            job_type=job_type,
            requirement=requirement,
            payload=payload,
            timeout=timeout,
            source=source,
            revision=revision,
        )
        submitter = Submitter(owner=owner, submitted_by=principal.subject_id)

        def operate(uow: UnitOfWork) -> SubmitResult:
            job, position = admit(
                uow, deps, definition=definition, submitter=submitter, placement=placement, retry_of=None
            )
            after: dict[str, object] = {"state": job.state.value, "position": position}
            if placement is None:
                after["retry_of"] = None
            else:
                after.update(placement_fields(placement))
            uow.audit.append(make_record(deps, principal, operation, job.job_id, after=after, on_behalf_of=behalf))
            return SubmitResult(job.job_id, position)

        return run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries)
