"""認証の依存関係(research.md R4、R5)。

`Authorization: Bearer` と Cookie から値を取り出して照合し、失敗は `401 authentication_failed` にする。
Cookie で認証された状態変更(POST/PUT/PATCH/DELETE)は、`Origin` が許可されたものでなければ
`403 origin_not_allowed`(CSRF の防止)。`Authorization` ヘッダの呼び出しには適用しない。
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request

from job_core.access.principal import Principal

from ..access.authenticate import Authenticated, AuthenticationFailed
from ..deps import ApiDependencies
from .errors import AuthenticationRequired, OriginNotAllowed

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_deps(request: Request) -> ApiDependencies:
    deps: ApiDependencies = request.app.state.deps
    return deps


Deps = Annotated[ApiDependencies, Depends(get_deps)]


def source_of(request: Request) -> str:
    """接続のアドレス(申告ヘッダは信用しない)。"""
    return request.client.host if request.client else "unknown"


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""  # 形式の誤り(空文字は認証の失敗として扱う)
    return value.strip()


def origin_allowed(request: Request, allowed_origins: tuple[str, ...]) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return False
    if allowed_origins:
        return origin in allowed_origins
    host = request.headers.get("host", "")
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return bool(host) and parts.scheme in {"http", "https"} and parts.netloc == host


def authenticate(request: Request, deps: Deps) -> Authenticated:
    header_token = bearer_token(request)
    via_cookie = header_token is None
    token = header_token if header_token is not None else request.cookies.get(deps.settings.cookie_name)
    try:
        result = deps.authenticator.authenticate(token, source=source_of(request))
    except AuthenticationFailed:
        raise AuthenticationRequired() from None
    if via_cookie and request.method in UNSAFE_METHODS and not origin_allowed(request, deps.settings.allowed_origins):
        raise OriginNotAllowed()
    request.state.principal_kind = result.principal.kind.value
    request.state.principal_id = result.principal.subject_id
    return result


Auth = Annotated[Authenticated, Depends(authenticate)]


def current_principal(auth: Auth) -> Principal:
    return auth.principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
