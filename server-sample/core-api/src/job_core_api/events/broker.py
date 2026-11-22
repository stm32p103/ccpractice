"""プロセス内の ChangeBroker(research.md R9。FR-017、FR-018)。

- 世代の識別子(epoch)はサーバーの起動ごとに新しくする。`seq` は世代内で単調増加(1 から)。
- 直近 N 件(既定 1000)をリングバッファに持つ。購読者ごとに送信待ちの列(既定 100)を持ち、超えたらその購読者を切断する。
- `publish` はブロックしない(購読者が遅くても、状態を変えるユースケースの応答を遅らせない)。
- API サーバーのプロセスは 1 つである前提(複数のプロセスでは通知の取りこぼしが起きる)。
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime

from .ports import ChangeEvent, ChangeType, PendingChange

TOPIC_OF: dict[ChangeType, str] = {
    ChangeType.JOB_CHANGED: "job",
    ChangeType.RUNNER_CHANGED: "runner",
    ChangeType.QUEUE_CHANGED: "queue",
}
ALL_TOPICS = frozenset(TOPIC_OF.values())


def parse_event_id(value: str | None) -> tuple[str, int] | None:
    """`<epoch>:<seq>` を分解する。不正な値は None。"""
    if not value or ":" not in value:
        return None
    epoch, _, seq_text = value.rpartition(":")
    if not epoch or not seq_text.isdigit():
        return None
    return epoch, int(seq_text)


class _Subscription:
    def __init__(self, topics: frozenset[str], capacity: int) -> None:
        self._topics = topics
        self._capacity = capacity
        self._items: deque[ChangeEvent] = deque()
        self._condition = threading.Condition()
        self._closed = False
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        self.on_close: Callable[[_Subscription], None] | None = None

    # ブローカー側 -----------------------------------------------------------

    def wants(self, event: ChangeEvent) -> bool:
        topic = TOPIC_OF.get(event.type)
        return topic is None or topic in self._topics

    def offer(self, event: ChangeEvent, *, initial: bool = False) -> bool:
        """非同期の購読者を含め、待たずに積む。送信待ちが上限を超えたら、この購読者を閉じる(False)。
        initial は、購読の開始時の再送(上限の対象外。再送の範囲は別の上限で決まる)。"""
        with self._condition:
            if self._closed:
                return False
            if not initial and len(self._items) >= self._capacity:
                self._closed = True
                self._items.clear()
                self._wake()
                return False
            self._items.append(event)
            self._wake()
            return True

    def _wake(self) -> None:
        self._condition.notify_all()
        for loop, flag in self._waiters:
            loop.call_soon_threadsafe(flag.set)

    # 購読者側 ---------------------------------------------------------------

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed and not self._items

    def close(self) -> None:
        with self._condition:
            already = self._closed
            self._closed = True
            self._wake()
        if not already and self.on_close is not None:
            self.on_close(self)

    def next(self, timeout: float) -> ChangeEvent | None:
        with self._condition:
            if not self._items and not self._closed:
                self._condition.wait(timeout)
            return self._items.popleft() if self._items else None

    async def next_async(self, timeout: float) -> ChangeEvent | None:
        loop = asyncio.get_running_loop()
        flag = asyncio.Event()
        with self._condition:
            if self._items:
                return self._items.popleft()
            if self._closed:
                return None
            self._waiters.append((loop, flag))
        try:
            await asyncio.wait_for(flag.wait(), timeout)
        except TimeoutError:
            pass
        finally:
            with self._condition:
                self._waiters = [w for w in self._waiters if w[1] is not flag]
        with self._condition:
            return self._items.popleft() if self._items else None


class InProcessChangeBroker:
    def __init__(
        self,
        *,
        replay_size: int = 1000,
        subscriber_queue: int = 100,
        now: Callable[[], datetime],
    ) -> None:
        self._epoch = uuid.uuid4().hex
        self._now = now
        self._buffer: deque[ChangeEvent] = deque(maxlen=replay_size)
        self._subscriber_queue = subscriber_queue
        self._subscribers: list[_Subscription] = []
        self._seq = 0
        self._lock = threading.Lock()

    @property
    def epoch(self) -> str:
        return self._epoch

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, change: PendingChange) -> None:
        with self._lock:
            self._seq += 1
            event = ChangeEvent(
                seq=self._seq,
                epoch=self._epoch,
                type=change.type,
                occurred_at=self._now(),
                subject=change.subject,
                state=change.state,
                change=change.change,
            )
            self._buffer.append(event)
            dropped = [s for s in self._subscribers if s.wants(event) and not s.offer(event)]
            for subscriber in dropped:
                self._subscribers.remove(subscriber)

    def subscribe(self, last_event_id: str | None, topics: frozenset[str] = ALL_TOPICS) -> _Subscription:
        subscription = _Subscription(frozenset(topics), self._subscriber_queue)
        subscription.on_close = self._remove
        with self._lock:
            if last_event_id is not None:
                for event in self._replay(last_event_id):
                    if subscription.wants(event):
                        subscription.offer(event, initial=True)
            self._subscribers.append(subscription)
        return subscription

    def _replay(self, last_event_id: str) -> list[ChangeEvent]:
        """続きが範囲内ならその分、範囲外・世代違い・不正な値なら resync(ロックを持った状態で呼ぶ)。"""
        parsed = parse_event_id(last_event_id)
        oldest = self._buffer[0].seq if self._buffer else self._seq + 1
        if parsed is None or parsed[0] != self._epoch or parsed[1] > self._seq or parsed[1] < oldest - 1:
            return [
                ChangeEvent(
                    seq=max(self._seq, 1),
                    epoch=self._epoch,
                    type=ChangeType.RESYNC,
                    occurred_at=self._now(),
                )
            ]
        return [event for event in self._buffer if event.seq > parsed[1]]

    def _remove(self, subscription: _Subscription) -> None:
        with self._lock:
            if subscription in self._subscribers:
                self._subscribers.remove(subscription)
