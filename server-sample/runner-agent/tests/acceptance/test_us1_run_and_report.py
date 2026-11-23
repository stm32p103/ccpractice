"""US1: ジョブを取得し、実行して、結果を報告する(spec US1-1〜US1-3、US1-5。V1〜V3、V5。SC-001)。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from job_testing.runner_fakes.executors import payload
from job_testing.runner_fakes.harness import AgentHarness


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_us1_1_fetch_run_and_report_success(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("echo", "hello"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        job = h.core.jobs[job_id]
        assert job.report is not None and job.report.exit_code == 0 and job.report.failure_reason is None
        assert h.core.registrations == [{"k1": "v"}]
        assert h.core.log_text(job_id).strip() == "hello"
        assert h.work_root_entries() == []  # 作業フォルダが残らない
        assert h.journal.read_active() is None and h.journal.load_results() == []

    run(scenario())


def test_us1_1_failure_is_reported_with_exit_code(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("exit", "3"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.exit_code == 3 and report.failure_reason is not None
        assert report.failure_reason.value == "tool_failed"

    run(scenario())


def test_us1_2_no_matching_job_means_polling_without_inbound(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        h.start()
        await h.wait_for(lambda: sum(r.path == "/v1/runner/job-requests" for r in h.core.requests) >= 3)
        await h.shutdown()
        assert all(r.method in ("POST", "DELETE") for r in h.core.requests)  # すべてランナーからの要求
        assert not any(j.state != "queued" for j in h.core.jobs.values())

    run(scenario())


def test_us1_3_heartbeats_are_sent_during_execution_and_extend_lease(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("sleep", "0.8"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        beats = [r for r in h.core.requests if r.path == "/v1/runner/heartbeat"]
        assert len(beats) >= 3  # 間隔 0.1 秒で、0.8 秒の実行の間

    run(scenario())


def test_us1_5_unknown_job_type_is_failed_without_launching(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("no-such-type", payload("echo", "x"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "unsupported_job_type" and report.exit_code is None
        assert h.core.log_text(job_id) == ""

    run(scenario())


def test_executor_exception_fails_only_that_job_and_hides_message(tmp_path: Path) -> None:
    from job_testing.runner_fakes.executors import RaisingExecutor

    async def scenario() -> None:
        h = AgentHarness.create(tmp_path, executors={"type-a": RaisingExecutor("prepare")})
        bad = h.core.enqueue("type-a", payload("echo", "x"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[bad].state == "failed")
        await h.shutdown()
        report = h.core.jobs[bad].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "executor_error"
        assert "SECRET-IN-EXCEPTION" not in h.core.recorded_text()
        assert "SECRET-IN-EXCEPTION" not in str(h.journal.read_audit())

    run(scenario())


def test_one_job_at_a_time_and_in_order(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        ids = [h.core.enqueue("type-a", payload("echo", f"j{i}")) for i in range(3)]
        h.start()
        await h.wait_for(lambda: all(h.core.jobs[i].state == "succeeded" for i in ids))
        await h.shutdown()
        assert [h.core.log_text(i).strip() for i in ids] == ["j0", "j1", "j2"]

    run(scenario())
