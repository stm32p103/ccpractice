"""時計・識別子のポートの実装(実時計と乱数。composition root が選ぶ)。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator:
    def new_id(self) -> str:
        return uuid.uuid4().hex
