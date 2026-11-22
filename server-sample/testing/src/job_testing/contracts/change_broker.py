"""ChangeBroker のポートの契約テスト(003 contracts/ports.md「ChangeBroker」)。

使い方: テストのクラスで継承し、`make_broker` フィクスチャ(replay_size と subscriber_queue を受けて
ChangeBroker を返す関数)を定義する。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest

from job_core_api.events.ports import (
    ChangeBroker,
    ChangeEvent,
    ChangeKind,
    ChangeSubject,
    ChangeType,
    PendingChange,
    SubjectKind,
    Subscription,
)

MakeBroker = Callable[..., ChangeBroker]
ALL = frozenset({"job", "runner", "queue"})


def job_change(job_id: str = "j1", change: ChangeKind = ChangeKind.SUBMITTED) -> PendingChange:
    return PendingChange(ChangeType.JOB_CHANGED, ChangeSubject(SubjectKind.JOB, job_id), "queued", change)


def drain(subscription: Subscription, limit: int = 100) -> list[ChangeEvent]:
    events: list[ChangeEvent] = []
    while len(events) < limit:
        event = subscription.next(0.0)
        if event is None:
            break
        events.append(event)
    return events


class ChangeBrokerContract:
    def test_seq_is_monotonic_from_one_within_an_epoch(self, make_broker: MakeBroker) -> None:
        broker = make_broker()
        subscription = broker.subscribe(None, ALL)
        for i in range(5):
            broker.publish(job_change(f"j{i}"))
        events = drain(subscription)
        assert [e.seq for e in events] == [1, 2, 3, 4, 5]
        assert {e.epoch for e in events} == {broker.epoch}
        assert events[0].event_id == f"{broker.epoch}:1"

    def test_a_new_subscription_without_last_event_id_gets_only_new_events(self, make_broker: MakeBroker) -> None:
        broker = make_broker()
        broker.publish(job_change())
        subscription = broker.subscribe(None, ALL)
        assert drain(subscription) == []
        broker.publish(job_change("j2"))
        assert [e.subject.id for e in drain(subscription) if e.subject] == ["j2"]

    def test_replay_from_inside_the_buffer(self, make_broker: MakeBroker) -> None:
        broker = make_broker()
        for i in range(5):
            broker.publish(job_change(f"j{i}"))
        subscription = broker.subscribe(f"{broker.epoch}:2", ALL)
        assert [e.seq for e in drain(subscription)] == [3, 4, 5]
        caught_up = broker.subscribe(f"{broker.epoch}:5", ALL)
        assert drain(caught_up) == []

    def test_out_of_range_or_other_epoch_or_invalid_ids_resync(self, make_broker: MakeBroker) -> None:
        broker = make_broker(replay_size=3)
        for i in range(10):
            broker.publish(job_change(f"j{i}"))
        for last_event_id in (f"{broker.epoch}:2", f"{broker.epoch}:99", "other-epoch:9", "garbage", ":", "x:y"):
            events = drain(broker.subscribe(last_event_id, ALL))
            assert [e.type for e in events] == [ChangeType.RESYNC], last_event_id
        inside = drain(broker.subscribe(f"{broker.epoch}:8", ALL))
        assert [e.seq for e in inside] == [9, 10]

    def test_epoch_differs_between_brokers(self, make_broker: MakeBroker) -> None:
        assert make_broker().epoch != make_broker().epoch

    def test_topic_filter(self, make_broker: MakeBroker) -> None:
        broker = make_broker()
        only_queue = broker.subscribe(None, frozenset({"queue"}))
        broker.publish(job_change())
        broker.publish(PendingChange(ChangeType.QUEUE_CHANGED))
        assert [e.type for e in drain(only_queue)] == [ChangeType.QUEUE_CHANGED]

    def test_slow_subscriber_is_disconnected_without_affecting_others_or_blocking_publish(
        self, make_broker: MakeBroker
    ) -> None:
        broker = make_broker(subscriber_queue=3)
        slow = broker.subscribe(None, ALL)
        fast = broker.subscribe(None, ALL)
        received = []
        for i in range(10):
            broker.publish(job_change(f"j{i}"))  # ブロックしない
            received.extend(drain(fast))
        assert [e.seq for e in received] == list(range(1, 11))
        assert slow.closed or drain(slow) == []
        assert slow.next(0.0) is None

    def test_closed_subscription_stops_receiving(self, make_broker: MakeBroker) -> None:
        broker = make_broker()
        subscription = broker.subscribe(None, ALL)
        subscription.close()
        broker.publish(job_change())
        assert subscription.next(0.0) is None and subscription.closed

    def test_pending_change_has_no_free_text_fields(self) -> None:
        assert {f.name for f in dataclasses.fields(PendingChange)} == {"type", "subject", "state", "change"}
        assert {f.name for f in dataclasses.fields(ChangeSubject)} == {"kind", "id"}
        for bad_state in ("has space", "UPPER", "a" * 40, "multi\nline", ""):
            with pytest.raises(ValueError):
                PendingChange(
                    ChangeType.JOB_CHANGED, ChangeSubject(SubjectKind.JOB, "j"), bad_state, ChangeKind.SUBMITTED
                )
        with pytest.raises(ValueError):
            PendingChange(ChangeType.JOB_CHANGED, ChangeSubject(SubjectKind.JOB, "x" * 129))
