"""固定・手動で進められる時計と、連番の識別子(contracts/ports.md「Clock / IdGenerator」の Fake)。"""

from __future__ import annotations

import itertools
import threading
from datetime import UTC, datetime, timedelta

DEFAULT_START = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)


class FakeClock:
    """呼び出すたびに tick だけ進む時計(既定は 1 ミリ秒。記録の時刻順が一意に決まるようにする)。"""

    def __init__(self, start: datetime = DEFAULT_START, tick: timedelta = timedelta(milliseconds=1)) -> None:
        if start.tzinfo is None:
            raise ValueError("start はタイムゾーン付きでなければならない")
        self._now = start.astimezone(UTC)
        self._tick = tick
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            current = self._now
            self._now = self._now + self._tick
            return current

    def peek(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self._now = self._now + delta

    def set(self, value: datetime) -> None:
        with self._lock:
            self._now = value.astimezone(UTC)


class SequentialIdGenerator:
    """prefix-000001 の形の連番。"""

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._counter = itertools.count(1)
        self._lock = threading.Lock()

    def new_id(self) -> str:
        with self._lock:
            return f"{self._prefix}-{next(self._counter):06d}"


class FakeSecretGenerator:
    """連番から決定的にトークンを作る(テストの再現性)。形は本物と同じ rt_ + 43 文字。"""

    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self._lock = threading.Lock()

    def new_token(self) -> str:
        with self._lock:
            number = next(self._counter)
        return "rt_" + f"{number:06d}".ljust(43, "x")
