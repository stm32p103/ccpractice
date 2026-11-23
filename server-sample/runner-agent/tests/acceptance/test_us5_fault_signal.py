"""US5・FR-023: ツールからの異常・回復の申告を、エージェントだけがコアへ送る(V24)。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from job_testing.runner_fakes.executors import payload
from job_testing.runner_fakes.harness import AgentHarness


def run_job(tmp_path: Path, *cmds: tuple[str, ...]):  # type: ignore[no-untyped-def]
    async def scenario():  # type: ignore[no-untyped-def]
        h = AgentHarness.create(tmp_path)
        ids = [h.core.enqueue("type-a", payload(*cmd)) for cmd in cmds]
        h.start()
        await h.wait_for(lambda: all(h.core.jobs[i].state == "succeeded" for i in ids))
        await h.shutdown()
        return h

    return asyncio.run(scenario())


def test_valid_fault_and_recovery_are_forwarded_by_the_agent(tmp_path: Path) -> None:
    h = run_job(tmp_path, ("fault", "冷却ファンの回転数が低下"), ("recovered",))
    assert h.core.faults == ["冷却ファンの回転数が低下", None]
    # ツールから PC の外へ送るものはない: コアへ届いたのはエージェントの要求だけ
    assert h.recorder is not None and h.recorder.hosts == {"fake-core.invalid"}


@pytest.mark.parametrize(
    "text",
    ["x" * 201, "line1\nline2", "bell\x07char", "   "],
)
def test_invalid_fault_content_is_not_sent_and_content_is_not_audited(tmp_path: Path, text: str) -> None:
    h = run_job(tmp_path, ("fault", text))
    assert h.core.faults == []
    events = [r for r in h.journal.read_audit() if r["event"] == "fault_signal_rejected"]
    assert len(events) == 1 and events[0]["reason"] == "invalid_content"
    assert text.strip() == "" or text[:20] not in json.dumps(h.journal.read_audit(), ensure_ascii=False)


def test_exactly_200_characters_is_accepted(tmp_path: Path) -> None:
    h = run_job(tmp_path, ("fault", "あ" * 200))
    assert h.core.faults == ["あ" * 200]


def test_signal_file_during_a_long_run_is_forwarded_while_running(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("sleep", "2.5"))  # 実行中に、ツールの代わりに signal へ直接書く
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "running")
        await asyncio.sleep(0.3)
        signal_dirs = list(Path(h.settings.work.root).glob("*/signal"))
        assert len(signal_dirs) == 1
        (signal_dirs[0] / "fault.txt").write_text("途中の異常", encoding="utf-8")
        await h.wait_for(lambda: h.core.faults == ["途中の異常"], timeout=10)
        assert h.core.jobs[job_id].state == "running"  # 実行中に転送された
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()

    asyncio.run(scenario())


def test_core_unavailable_keeps_the_signal_for_retry(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("sleep", "3"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "running")
        await asyncio.sleep(0.3)
        (next(Path(h.settings.work.root).glob("*/signal")) / "fault.txt").write_text("再送の確認", encoding="utf-8")
        h.core.fail_next = [503]  # 1 回目は到達できない
        await h.wait_for(lambda: h.core.faults == ["再送の確認"], timeout=15)
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()

    asyncio.run(scenario())
