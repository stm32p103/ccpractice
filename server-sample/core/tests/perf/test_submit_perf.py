"""性能の目安(SC-005 の core 部分。quickstart.md V9)。

待機中 500 件・ランナー 50 台の Fake で、提出の受付/拒否の判定が 50 ms 以下(95 パーセンタイル)。
DB を含む 2 秒の計測は 003 で行う。既定では実行しない(-m perf で実行)。
"""

from __future__ import annotations

import statistics
import time
from datetime import timedelta

import pytest

from job_core.access.permission import Permission
from job_core.access.principal import Principal
from job_core.job.application import DuplicateQueuedJob, NoEligibleRunner
from job_testing.core_fakes import build_core

pytestmark = pytest.mark.perf

LIMIT_SECONDS = 0.050


def test_submit_decision_is_fast_with_500_queued_and_50_runners() -> None:
    core = build_core()
    for i in range(50):
        core.runners.register(f"R{i}", {"os": f"os-{i % 5}", "slot": str(i)})
    alice = Principal.of("alice", [Permission.JOB_SUBMIT])
    for i in range(500):
        core.submit(
            alice,
            job_type="t",
            requirement={"os": f"os-{i % 5}"},
            payload={"i": i},
            timeout=timedelta(minutes=5),
            source=f"repo-{i}",
            revision="r",
        )

    samples: list[float] = []
    for i in range(40):
        started = time.perf_counter()
        kind = i % 3
        try:
            if kind == 0:  # 受付
                core.submit(alice, job_type="t", requirement={"os": "os-1"}, payload={}, timeout=timedelta(minutes=5))
            elif kind == 1:  # 重複で拒否
                core.submit(
                    alice,
                    job_type="t",
                    requirement={"os": "os-1"},
                    payload={},
                    timeout=timedelta(minutes=5),
                    source="repo-1",
                    revision="r",
                )
            else:  # 要件を満たすランナーがなく拒否
                core.submit(alice, job_type="t", requirement={"os": "none"}, payload={}, timeout=timedelta(minutes=5))
        except (DuplicateQueuedJob, NoEligibleRunner):
            pass
        samples.append(time.perf_counter() - started)

    p95 = statistics.quantiles(samples, n=20)[-1]
    assert p95 <= LIMIT_SECONDS, f"95 パーセンタイル {p95 * 1000:.1f} ms"
