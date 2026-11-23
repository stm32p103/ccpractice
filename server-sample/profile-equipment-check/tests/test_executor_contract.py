"""equipment-check のエグゼキュータが ExecutorContract を通る(T064)と、コアなしの単体試験(US5-3)。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_profile_equipment_check.executor import EquipmentCheckExecutor
from job_runner_agent.executor import ExecutorRejected, Literal, ProcessOutcome
from job_runner_agent.guard.workpath import PathRejected, WorkPath
from job_runner_protocol.vocabulary import FailureReason
from job_testing.contracts.executor import ExecutorContract, make_context


@pytest.fixture
def executor() -> EquipmentCheckExecutor:
    return EquipmentCheckExecutor()


@pytest.fixture
def valid_payloads() -> list[dict[str, Any]]:
    return [
        {"check": "link-test"},
        {"check": "link-test", "input": "cases\\a.json", "args": ["--fast", "--retries=2"]},
    ]


@pytest.fixture
def tool_ids() -> set[str]:
    return {"check-tool"}


class TestEquipmentCheckContract(ExecutorContract):
    pass


# ---------------------------------------------------------------- 単体(コアなし。US5-3)


def test_args_and_cwd_are_assembled(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, {"check": "link-test", "input": "cases\\a.json", "args": ["--fast"]})
    plan = EquipmentCheckExecutor().prepare(ctx)
    assert plan.tool_id == "check-tool" and plan.cwd == "work"
    texts = [a.value if isinstance(a, Literal) else a.rel for a in plan.args]
    assert texts == ["--check", "link-test", "--input", "src\\cases\\a.json", "--report", "work\\report.json", "--fast"]
    assert all(isinstance(a, (Literal, WorkPath)) for a in plan.args)
    assert "work\\report.json" in plan.artifact_patterns


def test_tool_id_comes_from_settings_options_only(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, {"check": "x"}, options={"tool_id": "other-tool"})
    assert EquipmentCheckExecutor().prepare(ctx).tool_id == "other-tool"
    # payload から tool_id を指定できない
    with pytest.raises(ExecutorRejected):
        EquipmentCheckExecutor().prepare(make_context(tmp_path, {"check": "x", "tool_id": "C:\\evil.exe"}))


@pytest.mark.parametrize("bad_input", ["..\\x", "C:\\Windows\\x", "\\\\h\\s\\x", "a:stream"])
def test_input_escaping_the_work_folder_is_rejected(tmp_path: Path, bad_input: str) -> None:
    with pytest.raises(PathRejected):
        EquipmentCheckExecutor().prepare(make_context(tmp_path, {"check": "x", "input": bad_input}))


@pytest.mark.parametrize(
    "payload",
    [
        {"check": "Bad Name"},
        {"check": "x" * 100},
        {"check": "x", "args": "no"},
        {"check": "x", "args": ["a"] * 17},
        {"check": "x", "input": ""},
    ],
)
def test_invalid_payload_shapes_are_rejected(tmp_path: Path, payload: dict[str, Any]) -> None:
    with pytest.raises(ExecutorRejected):
        EquipmentCheckExecutor().prepare(make_context(tmp_path, payload))


def test_result_interpretation(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, {"check": "x"})
    (ctx.work.root / "work" / "report.json").write_text(json.dumps({"passed": 7, "total": 9}))
    executor = EquipmentCheckExecutor()
    ok = executor.interpret(ctx, ProcessOutcome(0))
    assert ok.succeeded and ok.summary == "7/9 合格"
    failed = executor.interpret(ctx, ProcessOutcome(1))
    assert not failed.succeeded and failed.failure_reason is FailureReason.TOOL_FAILED and failed.summary == "7/9 合格"
    crashed = executor.interpret(ctx, ProcessOutcome(139))
    assert not crashed.succeeded and crashed.summary == "ツールの異常終了"


def test_malformed_report_is_ignored(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, {"check": "x"})
    report = ctx.work.root / "work" / "report.json"
    for content in ("not json", '{"passed": "7"}', '{"passed": true, "total": 1}', "x" * 70000):
        report.write_text(content)
        assert EquipmentCheckExecutor().interpret(ctx, ProcessOutcome(0)).summary is None
