"""境界のミドルウェア(research.md R10、R11)。

接続元の許可リスト(認証より前。接続のアドレスだけを見る)、`X-Request-Id`、応答ヘッダ、本文の上限、アクセスログ。
アクセスログは、メソッド・パス・状態コード・所要時間・request_id・主体の種類と識別子だけを出す
(`Authorization`・Cookie・クエリ・本文を出さない。T-A1)。
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from ..settings import ApiSettings
from .errors import PROBLEM_CONTENT_TYPE, NetworkNotAllowed, PayloadTooLarge, problem_for
from .versioning import version_headers

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
access_logger = logging.getLogger("job_core_api.access")


def _clean(value: object) -> str:
    """ログの注入を防ぐため、制御文字を無害化する。"""
    return str(value).encode("unicode_escape").decode("ascii")


class _BodyTooLarge(Exception):
    pass


def request_id_of(scope: Scope) -> str:
    state = scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")
        if isinstance(value, str):
            return value
    return "unknown"


class BoundaryMiddleware:
    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]], settings: ApiSettings) -> None:
        self._app = app
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        started = time.perf_counter()
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        supplied = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied if REQUEST_ID.match(supplied) else uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        status_holder = {"status": 0, "started": False}
        path = scope.get("path", "")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                status_holder["started"] = True
                out = list(message.get("headers", []))
                out.append((b"x-request-id", request_id.encode("ascii")))
                out.append((b"x-content-type-options", b"nosniff"))
                if path.startswith("/v1/"):
                    out.append((b"cache-control", b"no-store"))
                out.extend(version_headers(self._settings, path))
                message = {**message, "headers": out}
            await send(message)

        try:
            await self._handle(scope, receive, send_wrapper, headers, request_id)
        except _BodyTooLarge:
            if not status_holder["started"]:
                await self._problem(PayloadTooLarge(), request_id, send_wrapper)
        except Exception as exc:  # 登録済みの例外ハンドラーを通らなかった例外は internal_error(詳細なし)
            if not status_holder["started"]:
                await self._problem(exc, request_id, send_wrapper)
        finally:
            self._log(scope, status_holder["status"], time.perf_counter() - started, request_id)

    async def _handle(
        self, scope: Scope, receive: Receive, send: Send, headers: dict[bytes, bytes], request_id: str
    ) -> None:
        client = scope.get("client")
        address = client[0] if client else ""
        if not self._settings.network_allowed(address):
            await self._problem(NetworkNotAllowed(), request_id, send)
            return
        limit = self._settings.max_body_bytes
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = False
            if too_large:
                await self._problem(PayloadTooLarge(), request_id, send)
                return
        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        await self._app(scope, counting_receive, send)

    async def _problem(self, exc: Exception, request_id: str, send: Send) -> None:
        problem, extra_headers = problem_for(exc, request_id)
        body = json.dumps(problem.to_json(), ensure_ascii=False).encode("utf-8")
        headers = [(b"content-type", PROBLEM_CONTENT_TYPE.encode()), (b"content-length", str(len(body)).encode())]
        headers += [(k.lower().encode(), v.encode()) for k, v in extra_headers.items()]
        await send({"type": "http.response.start", "status": problem.status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _log(self, scope: Scope, status: int, elapsed: float, request_id: str) -> None:
        state = scope.get("state") or {}
        access_logger.info(
            "method=%s path=%s status=%s duration_ms=%d request_id=%s principal_kind=%s principal=%s",
            _clean(scope.get("method", "")),
            _clean(scope.get("path", "")),
            status,
            int(elapsed * 1000),
            request_id,
            _clean(state.get("principal_kind", "-")),
            _clean(state.get("principal_id", "-")),
        )
