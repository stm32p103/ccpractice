"""保持期間(data-model.md §6 RetentionPolicy.job_retention、RetentionPolicy.audit_retention)。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .errors import ValidationFailed

DEFAULT_JOB_RETENTION = timedelta(days=365)
DEFAULT_AUDIT_RETENTION = timedelta(days=1095)


@dataclass(frozen=True)
class RetentionPolicy:
    job_retention: timedelta = DEFAULT_JOB_RETENTION
    audit_retention: timedelta = DEFAULT_AUDIT_RETENTION

    def __post_init__(self) -> None:
        if self.job_retention <= timedelta(0):
            raise ValidationFailed("job_retention", "正の値でなければならない")
        if self.audit_retention <= timedelta(0):
            raise ValidationFailed("audit_retention", "正の値でなければならない")
        if self.audit_retention < self.job_retention:
            # 削除されたジョブの経緯を監査ログで追えるようにするため(FR-032)
            raise ValidationFailed("audit_retention", "ジョブの保持期間より短く設定できない")
