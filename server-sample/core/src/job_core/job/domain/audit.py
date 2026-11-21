"""監査ログの記録(data-model.md §4)。

項目: AuditRecord.record_id、.occurred_at、.actor、.actor_kind、.on_behalf_of、.operation、.job_id、
.before、.after、.reason、.outcome、.denial。追記専用で、記録は変更しない。
before / after には payload を入れない。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from job_core.access.principal import PrincipalKind
from job_core.shared.ids import JobId, SubjectId


class AuditOperation(StrEnum):
    SUBMIT = "submit"
    SUBMIT_PLACED = "submit_placed"
    RETRY = "retry"
    RESCHEDULE = "reschedule"
    CANCEL_QUEUED = "cancel_queued"
    ABORT_REQUEST = "abort_request"
    ABORT_CONFIRM = "abort_confirm"
    ASSIGN = "assign"
    COMPLETE = "complete"
    PURGE = "purge"
    READ_AUDIT_LOG = "read_audit_log"
    """監査ログ全体の閲覧。状態を変えないため、権限による拒否のときだけ記録する。"""


class AuditOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"


@dataclass(frozen=True)
class Denial:
    """拒否の内容。code は permission_denied または runner_mismatch。required は必要な権限の候補。"""

    code: str
    required: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditRecord:
    record_id: str
    occurred_at: datetime
    actor: SubjectId
    actor_kind: PrincipalKind
    operation: AuditOperation
    job_id: JobId | None
    outcome: AuditOutcome
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)
    reason: str | None = None
    on_behalf_of: SubjectId | None = None
    denial: Denial | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "before", dict(self.before))
        object.__setattr__(self, "after", dict(self.after))
        if (self.outcome is AuditOutcome.DENIED) != (self.denial is not None):
            raise ValueError("denial は outcome が DENIED のときだけ設定する")
