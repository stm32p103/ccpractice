"""PurgeExpired — 保持期間による削除(FR-031、FR-032。contracts/application-api.md「PurgeExpired」)。

定期実行の仕組みは 003 / 009 の責務。ここでは 1 回の削除だけを行う。
"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.retention import RetentionPolicy

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

        def operate(uow: UnitOfWork) -> PurgeResult:
            now = deps.clock.now()
            job_cutoff = now - effective.job_retention
            audit_cutoff = now - effective.audit_retention
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

        return run_in_unit_of_work(deps.uow_factory, operate, attempts=deps.max_conflict_retries)
