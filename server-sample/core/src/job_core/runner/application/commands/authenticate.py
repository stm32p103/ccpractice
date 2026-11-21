"""AuthenticateRunner — ランナーのトークンの照合(FR-024、FR-025。research.md R9)。

有効なら、ランナーの主体(権限は {runner.report, job.execute} に固定。FR-025)を返す。
未知・失効・削除済みは区別せず RunnerAuthenticationFailed とし、監査ログに DENIED(authentication_failed)を残す。
トークンの値・ハッシュは、記録にも例外にも入れない。
"""

from __future__ import annotations

from job_core.access.permission import Permission
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.domain.audit import AuditOperation
from job_core.runner.domain.errors import RunnerAuthenticationFailed
from job_core.runner.domain.token import hash_token
from job_core.shared.ids import RunnerId, SubjectId

from ..audit import ANONYMOUS, record_denial
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..uow_support import run_in_runner_uow

RUNNER_PERMISSIONS = frozenset({Permission.RUNNER_REPORT, Permission.JOB_EXECUTE})


class AuthenticateRunner:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, token: str) -> Principal:
        deps = self._deps
        if isinstance(token, str) and token:
            principal, runner_id = run_in_runner_uow(deps, lambda uow: self._lookup(uow, token))
            if principal is not None:
                return principal
        else:
            runner_id = None
        record_denial(
            deps,
            actor=ANONYMOUS,
            actor_kind=PrincipalKind.RUNNER,
            operation=AuditOperation.RUNNER_AUTHENTICATE,
            runner_id=runner_id,
            code=RunnerAuthenticationFailed.code,
        )
        raise RunnerAuthenticationFailed()

    @staticmethod
    def _lookup(uow: RunnerUnitOfWork, token: str) -> tuple[Principal | None, RunnerId | None]:
        candidate = hash_token(token)
        stored = uow.tokens.find_by_hash(candidate)
        if stored is None:
            return None, None
        runner = uow.runners.get(stored.runner_id)
        valid = not stored.is_revoked and stored.matches(candidate) and runner is not None and not runner.is_deleted
        if not valid:
            return None, stored.runner_id
        principal = Principal(
            subject_id=SubjectId(stored.runner_id), permissions=RUNNER_PERMISSIONS, kind=PrincipalKind.RUNNER
        )
        return principal, stored.runner_id
