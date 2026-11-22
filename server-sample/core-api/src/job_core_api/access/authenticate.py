"""認証(research.md R4): 値の先頭で種類を判別し、Principal を作る。

照合は呼び出しごとに行う(キャッシュしない)ため、失効は次の呼び出しから効く(T-A2)。
未知・失効・期限切れ・形式の誤りは区別せず AuthenticationFailed とし、失敗を監査ログに記録する(T-A7 の抑制つき)。
セッションの権限は、保存せず、現在の対応表で所属グループから導く(R5)。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta

from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application.ports import CoreDependencies
from job_core.job.domain.errors import ConcurrencyConflict
from job_core.runner.application.commands.authenticate import AuthenticateRunner
from job_core.shared.errors import JobCoreError
from job_core.shared.ids import SubjectId

from ..settings import ApiSettings
from .audit import AuthFailureAuditor
from .holder import AccessConfigHolder
from .models import Session
from .ports import ServiceCredentialRepository, SessionRepository
from .secrets import TokenKind, hash_token, hashes_equal, token_kind_of

TOUCH_INTERVAL = timedelta(minutes=1)
"""last_used_at の更新の間引き(呼び出しごとの更新が負荷になるのを避ける。無操作の期限の精度は 1 分程度)。"""


class AuthenticationFailed(Exception):
    """認証に失敗した。原因は区別しない。"""


@dataclass(frozen=True)
class Authenticated:
    principal: Principal
    session: Session | None = None
    """人間のセッションで認証されたときだけ。"""


class Authenticator:
    def __init__(
        self,
        *,
        deps: CoreDependencies,
        settings: ApiSettings,
        sessions: SessionRepository,
        credentials: ServiceCredentialRepository,
        access: AccessConfigHolder,
        authenticate_runner: AuthenticateRunner,
        auditor: AuthFailureAuditor,
    ) -> None:
        self._deps = deps
        self._settings = settings
        self._sessions = sessions
        self._credentials = credentials
        self._access = access
        self._authenticate_runner = authenticate_runner
        self._auditor = auditor

    def authenticate(self, token: str | None, *, source: str, touch: bool = True) -> Authenticated:
        """touch が False のとき、利用日時を更新しない(SSE の再確認は無操作の期限を延長しない)。"""
        kind = token_kind_of(token) if token else None
        if token is None or kind is None:
            self._auditor.record(source, "malformed")
            raise AuthenticationFailed()
        if kind is TokenKind.SESSION:
            return self._by_session(token, source, touch)
        if kind is TokenKind.SERVICE:
            return self._by_service(token, source, touch)
        return self._by_runner(token, source)

    def _by_session(self, token: str, source: str, touch: bool) -> Authenticated:
        now = self._deps.clock.now()
        candidate = hash_token(token)
        session = self._sessions.find_by_hash(candidate)
        if (
            session is None
            or not hashes_equal(session.token_hash, candidate)
            or not session.is_active(now, self._settings.session_idle_timeout)
        ):
            self._auditor.record(source, "session")
            raise AuthenticationFailed()
        if touch and now - session.last_used_at >= TOUCH_INTERVAL:
            self._sessions.touch(session.session_id, now)
            session = Session(
                session_id=session.session_id,
                token_hash=session.token_hash,
                subject_id=session.subject_id,
                groups=session.groups,
                created_at=session.created_at,
                last_used_at=now,
                expires_at=session.expires_at,
                display_name=session.display_name,
                revoked_at=session.revoked_at,
            )
        permissions = self._access.get().permissions_of(session.groups)
        principal = Principal(SubjectId(session.subject_id), permissions, PrincipalKind.HUMAN)
        return Authenticated(principal, session)

    def _by_service(self, token: str, source: str, touch: bool) -> Authenticated:
        now = self._deps.clock.now()
        candidate = hash_token(token)
        credential = self._credentials.find_by_hash(candidate)
        if credential is None or credential.is_revoked or not hashes_equal(credential.token_hash, candidate):
            self._auditor.record(source, "service")
            raise AuthenticationFailed()
        if touch and (credential.last_used_at is None or now - credential.last_used_at >= TOUCH_INTERVAL):
            # 利用日時の更新は補助。競合しても認証の結果は変えない
            with contextlib.suppress(ConcurrencyConflict):
                self._credentials.save(credential.used(now))
        # 設定の上限が後から狭まった場合に備え、現在の上限との共通部分だけを有効にする(最小権限)
        permissions = credential.permissions & self._access.get().service_permission_ceiling
        return Authenticated(Principal(credential.subject_id, permissions, PrincipalKind.SERVICE))

    def _by_runner(self, token: str, source: str) -> Authenticated:
        try:
            return Authenticated(self._authenticate_runner(token))
        except JobCoreError:
            # ランナーの失敗は 002 の RUNNER_AUTHENTICATE として記録済み
            raise AuthenticationFailed() from None
