"""再試行とバックオフ(research.md R13)。指数のバックオフ 1〜60 秒、±20% のゆらぎ。"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterator

from .core_client import CoreUnavailable

BASE_SECONDS = 1.0
MAX_SECONDS = 60.0
JITTER = 0.2


def backoff_delays(
    base: float = BASE_SECONDS, maximum: float = MAX_SECONDS, jitter: float = JITTER, rng: random.Random | None = None
) -> Iterator[float]:
    """1 回目 base、以降 2 倍で maximum まで。各値に ±jitter のゆらぎ。"""
    generator = rng or random.Random()
    delay = base
    while True:
        yield delay * (1 + generator.uniform(-jitter, jitter))
        delay = min(delay * 2, maximum)


async def retry_unavailable[T](
    operation: Callable[[], Awaitable[T]],
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    should_stop: Callable[[], bool] = lambda: False,
    delays: Iterator[float] | None = None,
    on_failure: Callable[[CoreUnavailable], None] | None = None,
) -> T | None:
    """CoreUnavailable の間、バックオフして再試行する。成功で結果を返す。should_stop が真なら None を返す。
    CoreRejected など他の例外は、そのまま送出する(確定の拒否の判断は呼び出し側)。"""
    sequence = delays if delays is not None else backoff_delays()
    while not should_stop():
        try:
            return await operation()
        except CoreUnavailable as exc:
            if on_failure is not None:
                on_failure(exc)
            await sleep(next(sequence))
    return None
