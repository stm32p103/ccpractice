"""認証・セッションのルーター(contracts/http-api.md §2.1。research.md R5)。

Cookie は `__Host-session`・HttpOnly・SameSite=Strict・Path=/(`Secure` は設定。外す場合は名前 `session`)。
`return_to` は同一オリジンの相対パスだけを許す(オープンリダイレクトの防止)。
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from ...access.authenticate import AuthenticationFailed
from ...access.sessions import LoggedIn
from ..authn import Auth, Deps, origin_allowed, source_of
from ..errors import AuthenticationRequired, NotFound, OriginNotAllowed, RequestInvalid, ReturnToInvalid
from ..schemas_auth import LoginRequest, SessionInfo

router = APIRouter(prefix="/auth", tags=["auth"])

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
DEFAULT_RETURN_TO = "/"
RETURN_TO_COOKIE_AGE = timedelta(minutes=10)


def validate_return_to(value: str) -> str:
    """同一オリジンの相対パス(`/` で始まり、`//`・`\\`・制御文字を含まない)だけを許す。"""
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or _CONTROL.search(value)
        or len(value) > 512
    ):
        raise ReturnToInvalid()
    return value


def _return_cookie_name(deps_cookie_name: str) -> str:
    return "__Host-return_to" if deps_cookie_name.startswith("__Host-") else "return_to"


def set_session_cookie(response: Response, deps: Deps, logged_in: LoggedIn) -> None:
    settings = deps.settings
    response.set_cookie(
        settings.cookie_name,
        logged_in.value,
        max_age=int(settings.session_absolute_timeout.total_seconds()),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response, deps: Deps) -> None:
    settings = deps.settings
    response.delete_cookie(
        settings.cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict"
    )


def session_info(auth: Auth, deps: Deps, *, token: str | None = None) -> SessionInfo:
    principal, session = auth.principal, auth.session
    return SessionInfo(
        principal_kind=principal.kind,
        subject_id=principal.subject_id,
        display_name=session.display_name if session else None,
        permissions=sorted(p.value for p in principal.permissions),
        expires_at=session.expires_at if session else None,
        idle_expires_at=session.idle_expires_at(deps.settings.session_idle_timeout) if session else None,
        session_token=token,
    )


@router.get("/login", status_code=302, response_class=RedirectResponse, operation_id="begin_login")
def begin_login(deps: Deps, return_to: Annotated[str, Query()] = DEFAULT_RETURN_TO) -> RedirectResponse:
    """認証基盤へ送る。遷移の要らない方式では 404。"""
    target = validate_return_to(return_to)
    redirect = deps.identity.begin_login(target)
    if redirect is None:
        raise NotFound()
    response = RedirectResponse(redirect.url, status_code=302)
    response.set_cookie(
        _return_cookie_name(deps.settings.cookie_name),
        target,
        max_age=int(RETURN_TO_COOKIE_AGE.total_seconds()),
        path="/",
        secure=deps.settings.cookie_secure,
        httponly=True,
        samesite="lax",  # 認証基盤からの戻り(別サイトからの遷移)で送られる必要がある
    )
    return response


@router.get("/callback", status_code=302, response_class=RedirectResponse, operation_id="complete_login")
def complete_login(request: Request, deps: Deps) -> RedirectResponse:
    """認証基盤からの戻り。全クエリを認証基盤の実装に渡し、セッションを作って Cookie を設定する。"""
    params = dict(request.query_params)
    try:
        logged_in = deps.session_service.login(params, source=source_of(request))
    except AuthenticationFailed:
        raise AuthenticationRequired() from None
    stored = request.cookies.get(_return_cookie_name(deps.settings.cookie_name), DEFAULT_RETURN_TO)
    try:
        target = validate_return_to(stored)
    except ReturnToInvalid:
        target = DEFAULT_RETURN_TO
    response = RedirectResponse(target, status_code=302)
    set_session_cookie(response, deps, logged_in)
    response.delete_cookie(_return_cookie_name(deps.settings.cookie_name), path="/")
    return response


@router.post("/login", response_model=SessionInfo, operation_id="login")
def login(body: LoginRequest, request: Request, response: Response, deps: Deps) -> SessionInfo:
    """直接の証明からセッションを作る(試験用の認証基盤、非ブラウザのクライアント用)。"""
    if "origin" in request.headers and not origin_allowed(request, deps.settings.allowed_origins):
        raise OriginNotAllowed()
    try:
        logged_in = deps.session_service.login(body.proof, source=source_of(request))
    except AuthenticationFailed:
        raise AuthenticationRequired() from None
    session = logged_in.session
    permissions = deps.access.get().permissions_of(session.groups)
    if body.delivery == "cookie":
        set_session_cookie(response, deps, logged_in)
    return SessionInfo(
        principal_kind="human",  # type: ignore[arg-type]
        subject_id=session.subject_id,
        display_name=session.display_name,
        permissions=sorted(p.value for p in permissions),
        expires_at=session.expires_at,
        idle_expires_at=session.idle_expires_at(deps.settings.session_idle_timeout),
        session_token=logged_in.value if body.delivery == "token" else None,
    )


@router.get("/session", response_model=SessionInfo, operation_id="get_session")
def get_session(auth: Auth, deps: Deps) -> SessionInfo:
    """呼び出した主体の情報(種類・識別子・権限・期限)。"""
    return session_info(auth, deps)


@router.delete("/session", status_code=204, operation_id="logout")
def logout(auth: Auth, deps: Deps) -> Response:
    """ログアウト(セッションの失効)。セッションで認証された呼び出しだけ。"""
    if auth.session is None:
        raise RequestInvalid()
    deps.session_service.logout(auth.session)
    response = Response(status_code=204)
    clear_session_cookie(response, deps)
    return response
