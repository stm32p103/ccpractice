"""GetAuditLog — 監査ログ全体の閲覧(US6、FR-026)。AUDIT_READ_ALL を要し、拒否も記録する。"""

from __future__ import annotations

from datetime import datetime

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation, AuditOutcome
from job_core.shared.ids import JobId, RunnerId, SubjectId

from ..audit_support import audited_denials
from ..authorization import authorize_audit_read_all
from ..ports import AuditFilter, CoreDependencies
from .audit_views import AuditLogPage, AuditRecordView

DEFAULT_LIMIT = 100


class GetAuditLog:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(
        self,
        principal: Principal,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        job_id: str | None = None,
        actor: str | None = None,
        operation: AuditOperation | str | None = None,
        outcome: AuditOutcome | str | None = None,
        runner_id: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> AuditLogPage:
        deps = self._deps
        audited_denials(
            deps, principal, AuditOperation.READ_AUDIT_LOG, None, lambda: authorize_audit_read_all(principal)
        )
        audit_filter = AuditFilter(
            since=since,
            until=until,
            job_id=JobId(job_id) if job_id is not None else None,
            actor=SubjectId(actor) if actor is not None else None,
            operation=AuditOperation(operation) if operation is not None else None,
            outcome=AuditOutcome(outcome) if outcome is not None else None,
            runner_id=RunnerId(runner_id) if runner_id is not None else None,
        )
        with deps.uow_factory() as uow:
            page = uow.audit.query(audit_filter, cursor, limit)
        return AuditLogPage(tuple(AuditRecordView.of(r) for r in page.items), page.next_cursor)
