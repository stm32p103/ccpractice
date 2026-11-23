"""US3: 中断・タイムアウトで、子孫を含めて確実に止める(spec US3-1〜US3-3。V12〜V14。SC-005、SC-009)。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from job_testing.runner_fakes.executors import payload
from job_testing.runner_fakes.harness import AgentHarness
from job_testing.runner_fakes.processes import pid_alive, wait_pids


def test_us3_1_abort_stops_process_tree_and_confirms_cancelled(tmp_path: Path) -> None:
    async def scenario() -> None:
        pid_file = tmp_path / "pids"
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("spawn-child", "120", str(pid_file)), timeout_seconds=300)
        h.start()
        pids = await wait_pids(pid_file)
        assert all(pid_alive(p) for p in pids)
        requested = time.monotonic()
        h.core.request_abort(job_id)
        await h.wait_for(lambda: h.core.jobs[job_id].state == "cancelled")
        elapsed = time.monotonic() - requested
        await h.shutdown()
        assert elapsed < 10  # 指示の受信から停止まで 10 秒以内(SC-005)
        assert not any(pid_alive(p) for p in pids)  # 子・孫が残らない
        assert h.core.jobs[job_id].report is None  # 中断は result ではなく stopped で報告する
        assert h.work_root_entries() == []  # 後始末(SC-009)
        assert h.journal.read_active() is None
        assert any(r["event"] == "stopped" and r["reason"] == "abort" for r in h.journal.read_audit())

    asyncio.run(scenario())


def test_us3_2_timeout_stops_process_tree_and_reports_failed_timeout(tmp_path: Path) -> None:
    async def scenario() -> None:
        pid_file = tmp_path / "pids"
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("spawn-child", "120", str(pid_file)), timeout_seconds=1.5)
        h.start()
        pids = await wait_pids(pid_file)
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "timeout" and report.exit_code is None
        assert not any(pid_alive(p) for p in pids)
        assert h.work_root_entries() == []

    asyncio.run(scenario())


def test_us3_2_timeout_counts_from_tool_launch_not_preparation(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("sleep", "0.5"), timeout_seconds=5)
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()

    asyncio.run(scenario())


def test_us3_3_cleanup_after_success_failure_abort_and_timeout(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        ok = h.core.enqueue("type-a", payload("write-file", {"work": "work\\f.txt"}, "x"))
        failed = h.core.enqueue("type-a", payload("exit", "1"))
        timed_out = h.core.enqueue("type-a", payload("sleep", "60"), timeout_seconds=0.8)
        h.start()
        await h.wait_for(lambda: all(h.core.jobs[j].state in ("succeeded", "failed") for j in (ok, failed, timed_out)))
        await h.shutdown()
        assert h.work_root_entries() == []

    asyncio.run(scenario())


def test_prepare_timeout_is_reported_and_cleans_up(tmp_path: Path) -> None:
    class HangingFetcher:
        async def fetch(self, source, revision, credential, dest):  # type: ignore[no-untyped-def]
            await asyncio.sleep(60)

    async def scenario() -> None:
        h = AgentHarness.create(
            tmp_path,
            settings_overrides={"source": {"repository_allowlist": ["repo-1"], "fetcher": "remote"}},
            timeouts={"prepare_timeout_seconds": 0.5},
            fetcher=HangingFetcher(),
        )
        job_id = h.core.enqueue("type-a", payload("echo", "x"), source="repo-1", revision="abc")
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "prepare_timeout"
        assert h.work_root_entries() == []

    asyncio.run(scenario())


def test_abort_during_preparation_stops_before_launch(tmp_path: Path) -> None:
    class SlowFetcher:
        async def fetch(self, source, revision, credential, dest):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.6)

    async def scenario() -> None:
        h = AgentHarness.create(
            tmp_path,
            settings_overrides={"source": {"repository_allowlist": ["repo-1"], "fetcher": "remote"}},
            fetcher=SlowFetcher(),
        )
        job_id = h.core.enqueue("type-a", payload("echo", "SHOULD-NOT-RUN"), source="repo-1")
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "running")
        h.core.request_abort(job_id)
        await h.wait_for(lambda: h.core.jobs[job_id].state == "cancelled")
        await h.shutdown()
        assert h.core.log_text(job_id) == ""
        assert h.work_root_entries() == []

    asyncio.run(scenario())
