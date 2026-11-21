"""監査記録の組み立てと、拒否の記録(research.md R9)。

権限による拒否(PermissionDenied)と、割り当て先でないランナーからの報告(RunnerMismatch)は、
本体の変更がないため、別の UoW で AuditLog.append_denied に記録する(FR-025)。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation, AuditOutcome, AuditRecord, Denial
from job_core.job.domain.errors import PermissionDenied, RunnerMismatch
from job_core.shared.ids import JobId, SubjectId

from .ports import CoreDependencies


def make_record(
    deps: CoreDependencies,
    principal: Principal,
    operation: AuditOperation,
    job_id: JobId | None,
    *,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
    on_behalf_of: SubjectId | None = None,
) -> AuditRecord:
    """成功した操作の監査記録を作る。"""
    return AuditRecord(
        record_id=deps.ids.new_id(),
        occurred_at=deps.clock.now(),
        actor=principal.subject_id,
        actor_kind=principal.kind,
        operation=operation,
        job_id=job_id,
        outcome=AuditOutcome.SUCCEEDED,
        before=before or {},
        after=after or {},
        reason=reason,
        on_behalf_of=on_behalf_of,
    )


def record_denied(
    deps: CoreDependencies,
    principal: Principal,
    operation: AuditOperation,
    job_id: JobId | None,
    error: PermissionDenied | RunnerMismatch,
    *,
    attempted: Mapping[str, Any] | None = None,
    on_behalf_of: SubjectId | None = None,
) -> None:
    """拒否を、別の UoW で記録する(呼び出し時点で独立に確定する)。"""
    required = error.required if isinstance(error, PermissionDenied) else ()
    record = AuditRecord(
        record_id=deps.ids.new_id(),
        occurred_at=deps.clock.now(),
        actor=principal.subject_id,
        actor_kind=principal.kind,
        operation=operation,
        job_id=job_id,
        outcome=AuditOutcome.DENIED,
        after=attempted or {},
        on_behalf_of=on_behalf_of,
        denial=Denial(code=error.code, required=tuple(required)),
    )
    with deps.uow_factory() as uow:
        uow.audit.append_denied(record)


def audited_denials[T](
    deps: CoreDependencies,
    principal: Principal,
    operation: AuditOperation,
    job_id: JobId | None,
    action: Callable[[], T],
    *,
    attempted: Mapping[str, Any] | None = None,
    on_behalf_of: SubjectId | None = None,
) -> T:
    """action を実行し、権限による拒否・割り当て先の不一致なら記録してから送出し直す。"""
    try:
        return action()
    except (PermissionDenied, RunnerMismatch) as error:
        record_denied(deps, principal, operation, job_id, error, attempted=attempted, on_behalf_of=on_behalf_of)
        raise
