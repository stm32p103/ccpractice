"""プロセス内の ChangeBroker に対する契約テスト(contracts/ports.md「ChangeBroker」)。"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime

import pytest

from job_core_api.events.broker import InProcessChangeBroker
from job_core_api.events.ports import ChangeType, PendingChange
from job_testing.contracts.change_broker import ALL, ChangeBrokerContract, MakeBroker


class TestInProcessChangeBroker(ChangeBrokerContract):
    @pytest.fixture
    def make_broker(self) -> MakeBroker:
        def make(replay_size: int = 1000, subscriber_queue: int = 100) -> InProcessChangeBroker:
            return InProcessChangeBroker(
                replay_size=replay_size, subscriber_queue=subscriber_queue, now=lambda: datetime.now(UTC)
            )

        return make


def make() -> InProcessChangeBroker:
    return InProcessChangeBroker(now=lambda: datetime.now(UTC))


def test_next_blocks_until_published_from_another_thread() -> None:
    broker = make()
    subscription = broker.subscribe(None, ALL)
    threading.Timer(0.05, lambda: broker.publish(PendingChange(ChangeType.QUEUE_CHANGED))).start()
    started = time.monotonic()
    event = subscription.next(2.0)
    assert event is not None and event.type is ChangeType.QUEUE_CHANGED and time.monotonic() - started < 1.5


def test_next_times_out_with_none() -> None:
    assert make().subscribe(None, ALL).next(0.05) is None


def test_async_next_is_woken_by_publish_from_a_worker_thread() -> None:
    broker = make()
    subscription = broker.subscribe(None, ALL)

    async def run() -> object:
        threading.Timer(0.05, lambda: broker.publish(PendingChange(ChangeType.QUEUE_CHANGED))).start()
        return await subscription.next_async(2.0)

    event = asyncio.run(run())
    assert event is not None and event.type is ChangeType.QUEUE_CHANGED  # type: ignore[attr-defined]


def test_async_next_times_out_and_wakes_on_close() -> None:
    broker = make()
    subscription = broker.subscribe(None, ALL)

    async def run() -> tuple[object, object]:
        timed_out = await subscription.next_async(0.05)
        threading.Timer(0.05, subscription.close).start()
        closed = await subscription.next_async(2.0)
        return timed_out, closed

    assert asyncio.run(run()) == (None, None)
    assert subscription.closed


def test_subscriber_count_follows_subscribe_and_close() -> None:
    broker = make()
    a, b = broker.subscribe(None, ALL), broker.subscribe(None, ALL)
    assert broker.subscriber_count == 2
    a.close()
    assert broker.subscriber_count == 1
    b.close()
    assert broker.subscriber_count == 0


def test_replay_larger_than_the_queue_is_delivered_in_full() -> None:
    broker = InProcessChangeBroker(replay_size=1000, subscriber_queue=5, now=lambda: datetime.now(UTC))
    for _ in range(50):
        broker.publish(PendingChange(ChangeType.QUEUE_CHANGED))
    subscription = broker.subscribe(f"{broker.epoch}:0", ALL)
    seen = []
    while (event := subscription.next(0.0)) is not None:
        seen.append(event.seq)
    assert seen == list(range(1, 51))
