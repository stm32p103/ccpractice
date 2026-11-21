"""GetJobHistory — ジョブごとの操作の経緯(US6、FR-026)。

対象のジョブの、成功した操作の記録だけを時刻順に返す(拒否の記録は含めない。US6-4)。
保持期間を過ぎてジョブが削除されていても、監査ログが残っていれば返す(FR-032 の目的)。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.errors import JobNotFound
from job_core.shared.ids import JobId

from ..authorization import authorize_view
from ..ports import CoreDependencies
from .audit_views import AuditRecordView


class GetJobHistory:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, job_id: str) -> tuple[AuditRecordView, ...]:
        authorize_view(principal)
        target = JobId(job_id)
        with self._deps.uow_factory() as uow:
            records = uow.audit.history_of(target)
            if not records and not uow.jobs.exists(target):
                raise JobNotFound(target)
            return tuple(AuditRecordView.of(record) for record in records)
