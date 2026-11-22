"""SSE の配信(research.md R9。contracts/http-api.md §2.7)。

接続の直後に `hello`、以後は通知を `id: <epoch>:<seq>` つきで送る。`heartbeat_seconds` ごとに `: keepalive` を送り、
そのたびに認証と `job.general` を再確認して、失われていれば `auth.expired` を送って閉じる(失効の検知は最大でこの間隔)。
再確認は無操作の期限を延長しない(SSE の接続だけでは延長しない。R5)。
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

from .ports import ChangeEvent, ChangeType, Subscription

AuthCheck = Callable[[], Awaitable[bool]]
Disconnected = Callable[[], Awaitable[bool]]


class SseConnections:
    """同時の接続数の上限(超えたら 503 sse_capacity_exceeded)。"""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._count = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self._count >= self._limit:
                return False
            self._count += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def count(self) -> int:
        with self._lock:
            return self._count


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def event_json(event: ChangeEvent) -> str:
    """配信する通知の JSON(contracts/change-event.schema.json)。項目は固定。"""
    body: dict[str, object] = {
        "seq": event.seq,
        "epoch": event.epoch,
        "type": event.type.value,
        "occurred_at": _iso(event.occurred_at),
    }
    if event.subject is not None:
        body["subject"] = {"kind": event.subject.kind.value, "id": event.subject.id}
    if event.state is not None:
        body["state"] = event.state
    if event.change is not None:
        body["change"] = event.change.value
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def format_event(event: ChangeEvent) -> str:
    return f"id: {event.event_id}\nevent: {event.type.value}\ndata: {event_json(event)}\n\n"


def format_hello(epoch: str, heartbeat_seconds: int) -> str:
    data = json.dumps({"epoch": epoch, "heartbeat_seconds": heartbeat_seconds}, separators=(",", ":"))
    return f"event: hello\ndata: {data}\n\n"


async def stream_events(
    subscription: Subscription,
    *,
    epoch: str,
    heartbeat_seconds: float,
    still_authorized: AuthCheck,
    disconnected: Disconnected,
    release: Callable[[], None],
    hello_seconds: int,
    now: Callable[[], datetime],
    last_seq: Callable[[], int],
) -> AsyncIterator[str]:
    """SSE の本文を順に作る。購読は終了時に必ず閉じ、接続の枠を返す。"""
    loop = asyncio.get_running_loop()
    try:
        yield format_hello(epoch, hello_seconds)
        last_check = loop.time()
        while True:
            remaining = heartbeat_seconds - (loop.time() - last_check)
            if remaining > 0:
                event = await subscription.next_async(remaining)
                if event is not None:
                    yield format_event(event)
                    continue
                if loop.time() - last_check < heartbeat_seconds:
                    if subscription.closed:
                        break  # 送信待ちの超過・購読の解除(再接続で補う)
                    continue
            # 一定の間隔ごと(通知が続いていても)の維持と、認証・権限の再確認
            last_check = loop.time()
            if subscription.closed or await disconnected():
                break
            yield ": keepalive\n\n"
            if not await still_authorized():
                expired = ChangeEvent(
                    seq=max(last_seq(), 1), epoch=epoch, type=ChangeType.AUTH_EXPIRED, occurred_at=now()
                )
                yield format_event(expired)
                break
    except asyncio.CancelledError:
        raise
    finally:
        subscription.close()
        release()
