"""RequestJob の性能の目安(spec SC-003 の core 部分。research.md R11)。

待機中 500 件・ランナー 50 台で、RequestJob が 50 ms 以下(95% 以上)。既定では実行しない(-m perf)。
"""

from __future__ import annotations

import statistics
import time

import pytest

from ..acceptance.runner.conftest import eq, make_env, requirement

pytestmark = pytest.mark.perf

QUEUED = 500
RUNNERS = 50
LIMIT_SECONDS = 0.050


def test_request_job_stays_within_budget_with_500_queued_and_50_runners() -> None:
    env = make_env()
    handles = [env.runner(f"r-{i:02d}", {"k1": f"v{i % 5}"}) for i in range(RUNNERS)]
    # 要件の合わないジョブを多く並べ、走査の最悪に近い状態にする(最後の数件だけが合う)
    for _ in range(QUEUED - 50):
        env.enqueue_raw(requirement(eq("k1", "none")))
    for index in range(50):
        env.enqueue_raw(requirement(eq("k1", f"v{index % 5}")))
    durations: list[float] = []
    for handle in handles:
        started = time.perf_counter()
        result = env.request(handle)
        durations.append(time.perf_counter() - started)
        assert result.assignment is not None
    durations.sort()
    p95 = durations[int(len(durations) * 0.95) - 1]
    assert p95 <= LIMIT_SECONDS, f"p95={p95 * 1000:.1f} ms(中央値 {statistics.median(durations) * 1000:.1f} ms)"
