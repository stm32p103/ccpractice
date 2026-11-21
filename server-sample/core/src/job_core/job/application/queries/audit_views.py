"""監査ログの表示用の型(data-model.md の AuditRecord の全項目。payload は元から含まない)。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from job_core.access.principal import PrincipalKind
from job_core.job.domain.audit import AuditOperation, AuditOutcome, AuditRecord
from job_core.shared.ids import JobId, RunnerId, SubjectId


@dataclass(frozen=True)
class AuditRecordView:
    record_id: str
    occurred_at: datetime
    actor: SubjectId
    actor_kind: PrincipalKind
    on_behalf_of: SubjectId | None
    operation: AuditOperation
    job_id: JobId | None
    before: Mapping[str, Any]
    after: Mapping[str, Any]
    reason: str | None
    outcome: AuditOutcome
    denial_code: str | None
    denial_required: tuple[str, ...]
    runner_id: RunnerId | None = None

    @classmethod
    def of(cls, record: AuditRecord) -> AuditRecordView:
        return cls(
            record_id=record.record_id,
            occurred_at=record.occurred_at,
            actor=record.actor,
            actor_kind=record.actor_kind,
            on_behalf_of=record.on_behalf_of,
            operation=record.operation,
            job_id=record.job_id,
            before=dict(record.before),
            after=dict(record.after),
            reason=record.reason,
            outcome=record.outcome,
            denial_code=record.denial.code if record.denial else None,
            denial_required=record.denial.required if record.denial else (),
            runner_id=record.runner_id,
        )


@dataclass(frozen=True)
class AuditLogPage:
    items: tuple[AuditRecordView, ...]
    next_cursor: str | None
