"""イベントの購読のルーター(contracts/http-api.md §2.7)。権限は `job.general`(API の層で判定する)。"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from job_core.access.permission import Permission
from job_core.job.domain.errors import PermissionDenied

from ...access.authenticate import AuthenticationFailed
from ...events.broker import ALL_TOPICS
from ...events.sse import stream_events
from ..authn import Auth, Deps, bearer_token, source_of
from ..errors import SseCapacityExceeded

router = APIRouter(tags=["events"])

TOPIC_VALUES = {"job", "runner", "queue"}


@router.get(
    "/events",
    operation_id="subscribe_events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}, "description": "変更の通知"}},
)
async def subscribe_events(
    request: Request,
    auth: Auth,
    deps: Deps,
    topics: Annotated[list[str] | None, Query(description="job、runner、queue の部分集合。既定はすべて")] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """状態の変更を購読する(text/event-stream)。再接続は `Last-Event-ID` で、取りこぼしを補う。"""
    if Permission.GENERAL not in auth.principal.permissions:
        raise PermissionDenied([Permission.GENERAL.value])
    broker = deps.broker
    if not deps.sse_connections.acquire():
        raise SseCapacityExceeded()
    selected = frozenset(t for t in (topics or ALL_TOPICS) if t in TOPIC_VALUES) or ALL_TOPICS
    subscription = broker.subscribe(last_event_id, selected)
    token = bearer_token(request)
    if token is None:
        token = request.cookies.get(deps.settings.cookie_name)
    source = source_of(request)

    def check() -> bool:
        """認証と job.general の再確認(無操作の期限は延長しない)。"""
        try:
            result = deps.authenticator.authenticate(token, source=source, touch=False)
        except AuthenticationFailed:
            return False
        return Permission.GENERAL in result.principal.permissions

    async def still_authorized() -> bool:
        return await asyncio.to_thread(check)

    body = stream_events(
        subscription,
        epoch=broker.epoch,
        heartbeat_seconds=deps.settings.sse_heartbeat_seconds,
        still_authorized=still_authorized,
        disconnected=request.is_disconnected,
        release=deps.sse_connections.release,
        hello_seconds=deps.settings.sse_heartbeat_seconds,
        now=deps.core.deps.clock.now,
        last_seq=lambda: broker.last_seq,
    )
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
