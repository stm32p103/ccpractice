"""例外ハンドラー(research.md R7)。すべての失敗を application/problem+json で返す。"""

from __future__ import annotations

import re
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from job_core.shared.errors import JobCoreError

from ..access.config import AccessConfigInvalid
from ..access.credentials import CredentialNotFoundError
from ..access.ports import DuplicateCredentialName, IdentityProviderUnavailable
from .errors import (
    PROBLEM_CONTENT_TYPE,
    ApiError,
    MethodNotAllowed,
    NotFound,
    RequestInvalid,
    problem_for,
    validation_errors,
)
from .middleware import request_id_of


def _template_matches(template: str, path: str) -> bool:
    """`/v1/jobs/{job_id}` のようなパスの雛形が、要求のパスに合うか。"""
    parts = re.split(r"\{[^/}]+\}", template)
    pattern = "[^/]+".join(re.escape(part) for part in parts)
    return re.fullmatch(pattern, path) is not None


def allowed_methods(request: Request) -> str:
    """要求のパスに合う OpenAPI のパスのメソッドの和集合(Starlette は最初のルートのメソッドしか示さないため)。"""
    methods: set[str] = set()
    for template, item in request.app.openapi().get("paths", {}).items():
        if _template_matches(template, request.url.path):
            methods |= {m.upper() for m in item if m in {"get", "put", "post", "delete", "patch"}}
    return ", ".join(sorted(methods))


def problem_response(
    exc: BaseException, request: Request, extra_headers: Mapping[str, str] | None = None
) -> JSONResponse:
    problem, headers = problem_for(exc, request_id_of(request.scope))
    return JSONResponse(
        problem.to_json(),
        status_code=problem.status,
        media_type=PROBLEM_CONTENT_TYPE,
        headers={**dict(headers), **(extra_headers or {})},
    )


async def _handle(request: Request, exc: Exception) -> JSONResponse:
    return problem_response(exc, request)


async def _handle_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return problem_response(RequestInvalid(validation_errors(list(exc.errors()))), request)


async def _handle_http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        return problem_response(NotFound(), request)
    if exc.status_code == 405:
        allow = allowed_methods(request)  # RFC 9110: Allow が必須。同じパスの全ルートの和集合にする
        return problem_response(MethodNotAllowed(), request, {"Allow": allow} if allow else None)
    return problem_response(RequestInvalid(), request)


def install_handlers(app: FastAPI) -> None:
    for exc_type in (
        ApiError,
        JobCoreError,
        AccessConfigInvalid,
        CredentialNotFoundError,
        DuplicateCredentialName,
        IdentityProviderUnavailable,
    ):
        app.add_exception_handler(exc_type, _handle)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
