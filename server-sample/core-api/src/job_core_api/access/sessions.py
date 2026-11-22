"""セッションのユースケース(research.md R5、R10。FR-005、FR-008、FR-012)。

ログイン = `IdentityProvider.complete_login` → セッションの作成。保存するのは所属グループで、権限は保存しない
(呼び出しごとに現在の対応表で導く)。値は発行の応答だけで返す。ログインのたびに新しい値を発行する(セッションの固定の防止)。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application.ports import CoreDependencies
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import PermissionDenied
from job_core.shared.ids import SubjectId

from ..settings import ApiSettings
from .audit import AuthFailureAuditor, append_success, make_audit_record, record_permission_denied
from .authenticate import AuthenticationFailed
from .holder import AccessConfigHolder
from .models import Session, VerifiedIdentity
from .ports import IdentityProvider, IdentityRejected, SessionRepository
from .secrets import TokenKind, hash_token, new_token

ACCESS_MANAGE = "access.manage"


@dataclass(frozen=True)
class LoggedIn:
    session: Session
    value: str
    """セッションの値(`ss_...`)。ログインの応答だけで返す。"""

    def __repr__(self) -> str:
        return f"LoggedIn(session_id={self.session.session_id!r}, value=***)"

    __str__ = __repr__


class SessionService:
    def __init__(
        self,
        *,
        deps: CoreDependencies,
        settings: ApiSettings,
        identity: IdentityProvider,
        sessions: SessionRepository,
        access: AccessConfigHolder,
        auditor: AuthFailureAuditor,
    ) -> None:
        self._deps = deps
        self._settings = settings
        self._identity = identity
        self._sessions = sessions
        self._access = access
        self._auditor = auditor

    def login(self, params: Mapping[str, str], *, source: str) -> LoggedIn:
        """認証基盤で本人性を確認してセッションを作る。確認できなければ AuthenticationFailed。"""
        try:
            identity = self._identity.complete_login(params)
        except IdentityRejected:
            self._auditor.record(source, "login")
            raise AuthenticationFailed() from None
        return self._create(identity)

    def logout(self, session: Session) -> None:
        now = self._deps.clock.now()
        self._sessions.revoke(session.session_id, now)
        principal = Principal(SubjectId(session.subject_id), frozenset(), PrincipalKind.HUMAN)
        append_success(self._deps, make_audit_record(self._deps, principal, AuditOperation.LOGOUT))

    def revoke_all_of(self, principal: Principal, *, subject_id: str) -> int:
        """指定した利用者のセッションをすべて失効させる(`access.manage`)。失効させた件数を返す。"""
        if ACCESS_MANAGE not in {p.value for p in principal.permissions}:
            record_permission_denied(
                self._deps, principal, AuditOperation.LOGOUT, (ACCESS_MANAGE,), {"subject_id": subject_id[:256]}
            )
            raise PermissionDenied([ACCESS_MANAGE])
        count = self._sessions.revoke_all_of(SubjectId(subject_id), self._deps.clock.now())
        record = make_audit_record(
            self._deps, principal, AuditOperation.LOGOUT, after={"subject_id": subject_id[:256], "revoked": count}
        )
        append_success(self._deps, record)
        return count

    def _create(self, identity: VerifiedIdentity) -> LoggedIn:
        now = self._deps.clock.now()
        value = new_token(TokenKind.SESSION)
        session = Session(
            session_id=self._deps.ids.new_id(),
            token_hash=hash_token(value),
            subject_id=identity.subject_id,
            groups=identity.groups,
            created_at=now,
            last_used_at=now,
            expires_at=now + self._settings.session_absolute_timeout,
            display_name=identity.display_name,
        )
        self._sessions.add(session)
        permissions = self._access.get().permissions_of(identity.groups)
        principal = Principal(identity.subject_id, permissions, PrincipalKind.HUMAN)
        append_success(self._deps, make_audit_record(self._deps, principal, AuditOperation.LOGIN))
        return LoggedIn(session, value)
