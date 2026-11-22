"""監査ログのモデル(contracts/http-api.md §2.4)。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from job_core.access.principal import PrincipalKind
from job_core.job.application import AuditLogPage, AuditOperation, AuditOutcome, AuditRecordView

from .schemas_jobs import ApiModel


class AuditRecordOut(ApiModel):
    record_id: str
    occurred_at: datetime
    actor: str
    actor_kind: PrincipalKind
    on_behalf_of: str | None
    operation: AuditOperation
    job_id: str | None
    before: dict[str, Any]
    after: dict[str, Any]
    reason: str | None
    outcome: AuditOutcome
    denial_code: str | None
    denial_required: list[str]
    runner_id: str | None

    @classmethod
    def of(cls, view: AuditRecordView) -> AuditRecordOut:
        return cls(
            record_id=view.record_id,
            occurred_at=view.occurred_at,
            actor=view.actor,
            actor_kind=view.actor_kind,
            on_behalf_of=view.on_behalf_of,
            operation=view.operation,
            job_id=view.job_id,
            before=dict(view.before),
            after=dict(view.after),
            reason=view.reason,
            outcome=view.outcome,
            denial_code=view.denial_code,
            denial_required=list(view.denial_required),
            runner_id=view.runner_id,
        )


class AuditLogPageOut(ApiModel):
    items: list[AuditRecordOut]
    next_cursor: str | None = Field(description="次の頁の cursor。null なら最後")

    @classmethod
    def of(cls, page: AuditLogPage) -> AuditLogPageOut:
        return cls(items=[AuditRecordOut.of(item) for item in page.items], next_cursor=page.next_cursor)
