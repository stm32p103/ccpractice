"""PurgeExpired — 保持期間による削除(FR-031、FR-032。contracts/application-api.md「PurgeExpired」)。

定期実行の仕組みは 003 / 009 の責務。ここでは 1 回の削除だけを行う。
"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.retention import RetentionPolicy
from job_core.job.domain.states import JobState

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_purge
from ..ports import CoreDependencies, UnitOfWork
from ..retry_policy import run_in_unit_of_work


@dataclass(frozen=True)
class PurgeResult:
    jobs_deleted: int
    audit_records_deleted: int


class PurgeExpired:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, policy: RetentionPolicy | None = None) -> PurgeResult:
        deps = self._deps
        effective = policy if policy is not None else RetentionPolicy()
        audited_denials(deps, principal, AuditOperation.PURGE, None, lambda: authorize_purge(principal))

        expired_ids: list[str] = []

        def operate(uow: UnitOfWork) -> PurgeResult:
            now = deps.clock.now()
            job_cutoff = now - effective.job_retention
            audit_cutoff = now - effective.audit_retention
            if deps.outputs is not None:  # 004: ログ・成果物の参照も、ジョブと同じ保持期間で削除する
                terminal = [s for s in JobState if s.is_terminal]
                expired_ids[:] = [
                    str(job.job_id)
                    for job in uow.jobs.list_by_states(terminal, None, None).items
                    if job.finished_at is not None and job.finished_at < job_cutoff
                ]
            jobs_deleted = uow.jobs.delete_finished_before(job_cutoff)
            audit_deleted = uow.audit.delete_before(audit_cutoff)
            uow.audit.append(
                make_record(
                    deps,
                    principal,
                    AuditOperation.PURGE,
                    None,
                    after={
                        "jobs_deleted": jobs_deleted,
                        "audit_records_deleted": audit_deleted,
                        "cutoffs": {"jobs": job_cutoff.isoformat(), "audit": audit_cutoff.isoformat()},
                    },
                )
            )
            return PurgeResult(jobs_deleted, audit_deleted)

        result = run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries)
        if deps.outputs is not None:
            for job_id in expired_ids:
                deps.outputs.purge(job_id)  # type: ignore[arg-type]
        return result
