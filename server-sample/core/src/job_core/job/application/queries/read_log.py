"""ReadLog・ListArtifacts — ログ・成果物の参照の閲覧(004 contracts/runner-protocol.md §2)。

権限 JOB_READ_OUTPUT。閲覧は監査に残す(LOG_READ・ARTIFACT_READ。誰が・いつ・どのジョブを。内容は記録しない)。
"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import JobNotFound, ValidationFailed
from job_core.job.domain.output import JobArtifactRef, StoredLogChunk
from job_core.shared.ids import JobId

from ..audit_support import audited_denials, make_record
from ..authorization import authorize_read_output
from ..ports import CoreDependencies

MAX_PAGE = 1000
DEFAULT_PAGE = 200


@dataclass(frozen=True)
class LogPageView:
    chunks: tuple[StoredLogChunk, ...]
    next_seq: int
    complete: bool
    """ジョブが終了し、すべてのチャンクを返した。"""


class ReadLog:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(
        self, principal: Principal, *, job_id: str, after_seq: int = -1, limit: int = DEFAULT_PAGE
    ) -> LogPageView:
        deps = self._deps
        outputs = deps.outputs
        if outputs is None:
            raise ValidationFailed("outputs", "ログの保存先が構成されていない")
        if isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE:
            raise ValidationFailed("limit", "1 以上 1000 以下でなければならない")
        if isinstance(after_seq, bool) or after_seq < -1:
            raise ValidationFailed("after_seq", "-1 以上でなければならない")
        target = JobId(job_id)

        def operate() -> LogPageView:
            authorize_read_output(principal)
            with deps.uow_factory() as uow:
                job = uow.jobs.get(target)
                if job is None:
                    raise JobNotFound(target)
                finished = job.state.is_terminal
                uow.audit.append(make_record(deps, principal, AuditOperation.LOG_READ, target))
                uow.commit()
            chunks = outputs.read(target, after_seq, limit + 1)
            more = len(chunks) > limit
            page = chunks[:limit]
            next_seq = page[-1].seq + 1 if page else after_seq + 1
            return LogPageView(tuple(page), next_seq, finished and not more)

        return audited_denials(deps, principal, AuditOperation.LOG_READ, target, operate)


class ListArtifacts:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, job_id: str) -> tuple[JobArtifactRef, ...]:
        deps = self._deps
        outputs = deps.outputs
        if outputs is None:
            raise ValidationFailed("outputs", "ログの保存先が構成されていない")
        target = JobId(job_id)

        def operate() -> tuple[JobArtifactRef, ...]:
            authorize_read_output(principal)
            with deps.uow_factory() as uow:
                if uow.jobs.get(target) is None:
                    raise JobNotFound(target)
                uow.audit.append(make_record(deps, principal, AuditOperation.ARTIFACT_READ, target))
                uow.commit()
            return tuple(outputs.list_artifacts(target))

        return audited_denials(deps, principal, AuditOperation.ARTIFACT_READ, target, operate)
