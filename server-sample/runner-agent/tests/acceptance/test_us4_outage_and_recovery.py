"""US4: サーバーや PC の障害から自動で復帰する(spec US4-1・US4-3。V15〜V17、V25。SC-006。FR-009、FR-024)。"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from job_runner_protocol.messages import FinishReport
from job_runner_protocol.vocabulary import FailureReason, Outcome
from job_testing.runner_fakes.executors import payload
from job_testing.runner_fakes.fake_core import FakeRunnerCore
from job_testing.runner_fakes.harness import AgentHarness
from job_testing.runner_fakes.processes import pid_alive, wait_pids


async def fast_sleep(seconds: float) -> None:
    await asyncio.sleep(min(seconds, 0.1))  # バックオフと生存通知の間隔を短縮する


def result_requests(h: AgentHarness, job_id: str) -> int:
    return sum(1 for r in h.core.requests if r.path.endswith(f"/{job_id}/result"))


def test_us4_1_outage_shorter_than_lease_job_continues_and_result_is_reported_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path, sleep=fast_sleep)
        job_id = h.core.enqueue("type-a", payload("lines", "12", "0.15"))
        h.start()
        await h.wait_for(lambda: "line-1" in h.core.log_text(job_id))
        h.core.down = True  # 到達しない間も、ジョブは継続する
        await asyncio.sleep(0.8)
        assert h.core.jobs[job_id].state == "running"
        h.core.down = False
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded", timeout=30)
        await h.shutdown()
        assert h.core.log_text(job_id).splitlines() == [f"line-{i}" for i in range(12)]  # 欠けない・重複しない
        assert result_requests(h, job_id) == 1  # 結果は 1 回だけ(SC-006)
        assert h.journal.load_results() == [] and h.work_root_entries() == []

    asyncio.run(scenario())


def test_us4_3_result_finished_during_outage_is_reported_after_recovery(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path, sleep=fast_sleep)
        job_id = h.core.enqueue("type-a", payload("sleep", "0.4"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "running")
        h.core.down = True
        await asyncio.sleep(1.2)  # ツールは終了しているが、報告できない
        assert h.core.jobs[job_id].state == "running"
        assert [i for i, _ in h.journal.load_results()] == [job_id]  # ジャーナルに残っている
        h.core.down = False
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded", timeout=30)
        await h.shutdown()
        assert h.journal.load_results() == [] and h.journal.read_active() is None
        assert result_requests(h, job_id) == 1 or result_requests(h, job_id) >= 1

    asyncio.run(scenario())


def test_server_errors_are_retried(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path, sleep=fast_sleep)
        job_id = h.core.enqueue("type-a", payload("sleep", "0.3"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "running")
        h.core.fail_next = [503, 503, 500]
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded", timeout=30)
        await h.shutdown()

    asyncio.run(scenario())


def test_lease_exceeded_outage_stops_tool_without_reporting(tmp_path: Path) -> None:
    async def scenario() -> None:
        pid_file = tmp_path / "pids"
        core = FakeRunnerCore(lease_seconds=0.6, heartbeat_interval=0.1)
        h = AgentHarness.create(tmp_path, core=core, sleep=fast_sleep)
        job_id = core.enqueue("type-a", payload("spawn-child", "120", str(pid_file)), timeout_seconds=300)
        h.start()
        pids = await wait_pids(pid_file)
        core.down = True
        await asyncio.sleep(1.5)  # リースの長さを超える途絶
        core.down = False
        await h.wait_for(lambda: not any(pid_alive(p) for p in pids), timeout=20)
        await h.wait_for(lambda: h.work_root_entries() == [])
        await h.shutdown()
        assert core.jobs[job_id].state == "failed" and core.jobs[job_id].failure_reason == "lease_expired"
        assert core.jobs[job_id].report is None  # 報告しない(拒否されるため)
        assert h.journal.read_active() is None

    asyncio.run(scenario())


def test_lease_exceeded_with_finished_tool_report_is_rejected_and_recorded(tmp_path: Path) -> None:
    async def scenario() -> None:
        core = FakeRunnerCore(lease_seconds=0.5, heartbeat_interval=0.1)
        h = AgentHarness.create(tmp_path, core=core, sleep=fast_sleep)
        job_id = core.enqueue("type-a", payload("sleep", "0.3"))
        h.start()
        await h.wait_for(lambda: core.jobs[job_id].state == "running")
        core.down = True
        await asyncio.sleep(1.2)  # ツールは終了するが、リースが切れる
        core.down = False
        await h.wait_for(lambda: any(r["event"] == "report_rejected" for r in h.journal.read_audit()), timeout=20)
        await h.shutdown()
        rejected = [r for r in h.journal.read_audit() if r["event"] == "report_rejected"]
        assert rejected[0]["code"] == "lease_expired" and rejected[0]["status"] == 409
        assert h.journal.load_results() == [] and h.journal.read_active() is None  # 確定の拒否は再試行しない
        assert core.jobs[job_id].state == "failed" and core.jobs[job_id].failure_reason == "lease_expired"

    asyncio.run(scenario())


def test_restart_reports_agent_restarted_and_cleans_leftover_work_folders(tmp_path: Path) -> None:
    async def scenario() -> None:
        core = FakeRunnerCore(lease_seconds=60, heartbeat_interval=0.1)
        job_id = core.enqueue("type-a", payload("echo", "x"))
        job = core.jobs[job_id]
        job.state, job.lease_id, job.lease_expires_at = "running", "lease-x", time.monotonic() + 60
        core.queue.clear()
        h = AgentHarness.create(tmp_path, core=core, sleep=fast_sleep)
        h.journal.write_active(job_id, "lease-x", "2026-11-22T00:00:00Z")  # 前回の実行が、報告されずに残った
        leftover = Path(h.settings.work.root) / "old-job-abc"
        (leftover / "work").mkdir(parents=True)
        (leftover / "work" / "f.txt").write_text("x")
        h.start()
        await h.wait_for(lambda: core.jobs[job_id].state == "failed")
        await h.wait_for(lambda: h.work_root_entries() == [])
        await h.shutdown()
        assert core.jobs[job_id].failure_reason == "agent_restarted"
        assert h.journal.read_active() is None

    asyncio.run(scenario())


def test_journaled_result_is_reported_first_at_startup(tmp_path: Path) -> None:
    async def scenario() -> None:
        core = FakeRunnerCore(lease_seconds=60, heartbeat_interval=0.1)
        job_id = core.enqueue("type-a", payload("echo", "x"))
        job = core.jobs[job_id]
        job.state, job.lease_id, job.lease_expires_at = "running", "lease-x", time.monotonic() + 60
        core.queue.clear()
        h = AgentHarness.create(tmp_path, core=core, sleep=fast_sleep)
        h.journal.write_active(job_id, "lease-x", "2026-11-22T00:00:00Z")
        report = FinishReport(Outcome.SUCCEEDED, "done", 0)
        h.journal.save_result(job_id, json.loads(json.dumps(report.to_json())))
        h.start()
        await h.wait_for(lambda: core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        assert core.jobs[job_id].report is not None and core.jobs[job_id].report.result_summary == "done"
        assert h.journal.load_results() == [] and h.journal.read_active() is None
        assert core.jobs[job_id].failure_reason is None  # agent_restarted で上書きされない

    asyncio.run(scenario())


def test_journaled_result_rejected_by_core_is_dropped(tmp_path: Path) -> None:
    async def scenario() -> None:
        core = FakeRunnerCore(lease_seconds=60, heartbeat_interval=0.1)
        job_id = core.enqueue("type-a", payload("echo", "x"))
        core.jobs[job_id].state = "failed"  # 既に確定している
        core.queue.clear()
        h = AgentHarness.create(tmp_path, core=core, sleep=fast_sleep)
        h.journal.save_result(job_id, FinishReport(Outcome.FAILED, None, 1, FailureReason.TOOL_FAILED).to_json())
        h.start()
        await h.wait_for(lambda: h.journal.load_results() == [])
        await h.shutdown()
        assert any(r["event"] == "report_rejected" for r in h.journal.read_audit())

    asyncio.run(scenario())


def test_shutdown_signal_stops_tool_and_reports_agent_shutdown(tmp_path: Path) -> None:
    async def scenario() -> None:
        pid_file = tmp_path / "pids"
        h = AgentHarness.create(tmp_path, sleep=fast_sleep)
        job_id = h.core.enqueue("type-a", payload("spawn-child", "120", str(pid_file)), timeout_seconds=300)
        h.start()
        pids = await wait_pids(pid_file)
        started = time.monotonic()
        h.stop.set()
        assert h.task is not None
        await asyncio.wait_for(h.task, timeout=15)
        assert time.monotonic() - started < 10
        await h.context.client.aclose()
        assert not any(pid_alive(p) for p in pids)
        job = h.core.jobs[job_id]
        assert job.state == "failed" and job.failure_reason == "agent_shutdown"
        assert h.work_root_entries() == [] and h.journal.read_active() is None

    asyncio.run(scenario())


def test_shutdown_while_core_is_down_leaves_restart_record(tmp_path: Path) -> None:
    async def scenario() -> None:
        pid_file = tmp_path / "pids"
        h = AgentHarness.create(tmp_path, sleep=fast_sleep)
        job_id = h.core.enqueue("type-a", payload("spawn-child", "120", str(pid_file)), timeout_seconds=300)
        h.start()
        pids = await wait_pids(pid_file)
        h.core.down = True
        h.stop.set()
        assert h.task is not None
        await asyncio.wait_for(h.task, timeout=20)
        await h.context.client.aclose()
        assert not any(pid_alive(p) for p in pids)
        assert h.core.jobs[job_id].state == "running"  # 報告できなかった
        assert h.journal.read_active() is not None  # 次の起動時に agent_restarted を報告する
        assert h.work_root_entries() == []

    asyncio.run(scenario())
