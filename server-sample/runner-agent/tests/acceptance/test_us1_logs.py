"""US1-4: ログがコアへ逐次送信され、再送しても重複しない(V4。FR-004)。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from job_testing.runner_fakes.executors import payload
from job_testing.runner_fakes.harness import AgentHarness


def test_us1_4_logs_arrive_incrementally_with_contiguous_seq(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("lines", "6", "0.3"))
        h.start()
        # 実行の途中で、先頭の行がもう届いている(逐次)
        await h.wait_for(lambda: "line-0" in h.core.log_text(job_id))
        assert h.core.jobs[job_id].state == "running"
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        seqs = sorted(h.core.jobs[job_id].logs)
        assert seqs == list(range(len(seqs))) and len(seqs) >= 2
        assert h.core.log_text(job_id).splitlines() == [f"line-{i}" for i in range(6)]

    asyncio.run(scenario())


def test_stdout_and_stderr_are_kept_apart(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("err", "to-stderr"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        streams = {stream for stream, _ in h.core.jobs[job_id].logs.values()}
        assert streams == {"stderr"}

    asyncio.run(scenario())


def test_lost_responses_are_retried_without_duplicates(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        h.core.drop_log_responses = 2  # 保存した上で応答を落とす
        job_id = h.core.enqueue("type-a", payload("lines", "3", "0.0"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded", timeout=30)
        await h.shutdown()
        assert h.core.log_text(job_id).splitlines() == ["line-0", "line-1", "line-2"]

    asyncio.run(scenario())


def test_log_volume_over_the_limit_is_truncated_and_reported(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(
            tmp_path, settings_overrides={"logs": {"max_bytes_per_job": 2000, "max_bytes_per_second": 1048576}}
        )
        job_id = h.core.enqueue("type-a", payload("lines", "400", "0.0"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded", timeout=30)
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.counters.log_truncated
        text = h.core.log_text(job_id)
        assert len(text) <= 2000 + 64 and "[出力を切り詰めました]" in text
        assert "line-399" not in text

    asyncio.run(scenario())


def test_core_quota_stops_sending_but_job_completes(tmp_path: Path) -> None:
    async def scenario() -> None:
        from job_testing.runner_fakes.fake_core import FakeRunnerCore

        core = FakeRunnerCore(lease_seconds=60, heartbeat_interval=0.1, log_quota_chars=30)
        h = AgentHarness.create(tmp_path, core=core)
        job_id = core.enqueue("type-a", payload("lines", "50", "0.0"))
        h.start()
        await h.wait_for(lambda: core.jobs[job_id].state == "succeeded", timeout=30)
        await h.shutdown()
        report = core.jobs[job_id].report
        assert report is not None and report.counters.log_truncated
        assert len(core.log_text(job_id)) <= 30

    asyncio.run(scenario())
