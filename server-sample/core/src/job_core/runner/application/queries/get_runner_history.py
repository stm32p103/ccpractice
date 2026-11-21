"""GetRunnerHistory — ランナーごとの操作の経緯(spec FR-029。001 FR-026 に倣う)。

すべての利用者(job.general)が、成功した操作の記録(作成・登録・状態の変更・削除・トークンの発行と失効・
リース切れ・割り当てなど。操作者・日時・変更前後の値・理由)を時刻順に確認できる。
権限・認証・申告の検査による拒否の記録は含めない(拒否を含む監査ログ全体は、001 の GetAuditLog(audit.read_all))。
削除済みのランナーでも、記録が残っていれば返す。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.application.ports import AuditFilter
from job_core.job.application.queries.audit_views import AuditRecordView
from job_core.job.domain.audit import AuditOutcome
from job_core.runner.domain.errors import RunnerNotFound
from job_core.shared.ids import RunnerId

from ..authorization import authorize_view
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..uow_support import run_in_runner_uow

PAGE_SIZE = 500


class GetRunnerHistory:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str) -> tuple[AuditRecordView, ...]:
        authorize_view(principal)
        target = RunnerId(runner_id)

        def read(uow: RunnerUnitOfWork) -> tuple[AuditRecordView, ...]:
            records = []
            cursor: str | None = None
            while True:
                page = uow.audit.query(AuditFilter(runner_id=target, outcome=AuditOutcome.SUCCEEDED), cursor, PAGE_SIZE)
                records.extend(page.items)
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
            if not records and uow.runners.get(target) is None:
                raise RunnerNotFound(runner_id)
            return tuple(AuditRecordView.of(record) for record in records)

        return run_in_runner_uow(self._deps, read)
