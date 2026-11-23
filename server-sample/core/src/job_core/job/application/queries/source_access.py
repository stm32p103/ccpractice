"""ResolveSourceAccess — 取得資格の発行の前提の確認(004 contracts/runner-protocol.md §3.2)。

割り当て先のランナー(JOB_EXECUTE)が、実行中のジョブのソースの取得を求めたときに、取得資格の対象(source・revision)を返す。
資格の発行そのものは、コアの外のポート(SourceCredentialIssuer。core-api)が行う。
"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import JobNotFound, RunnerMismatch, TargetNotRunning
from job_core.job.domain.states import JobState
from job_core.shared.ids import JobId, RunnerId

from ..audit_support import audited_denials
from ..authorization import authorize_execute
from ..ports import CoreDependencies


@dataclass(frozen=True)
class SourceTarget:
    source: str | None
    revision: str | None


class ResolveSourceAccess:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, job_id: str) -> SourceTarget:
        deps = self._deps
        target = JobId(job_id)
        runner = RunnerId(runner_id)

        def operate() -> SourceTarget:
            authorize_execute(principal)
            with deps.uow_factory() as uow:
                job = uow.jobs.get(target)
            if job is None:
                raise JobNotFound(target)
            if job.state is not JobState.RUNNING:
                raise TargetNotRunning(target, job.state.value)
            if job.assigned_runner_id != runner:
                raise RunnerMismatch(target)
            ref = job.definition.source_ref
            return SourceTarget(ref.source if ref else None, ref.revision if ref else None)

        return audited_denials(
            deps, principal, AuditOperation.RUNNER_JOB_REPORT, target, operate, attempted={"runner_id": runner}
        )
