"""Executor の契約テスト(004 contracts/ports.md「Executor」)。

使い方: `executor`(Executor)と、`valid_payloads`(受け付けられる payload の一覧)と `tool_ids`(許可する tool_id)の
フィクスチャを定義して、このクラスを継承する。用途ごとのエグゼキュータが、同じテストを通る。
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from job_runner_agent.artifacts.collect import compile_pattern
from job_runner_agent.executor import (
    ExecutionContext,
    Executor,
    ExecutorRejected,
    Literal,
    ProcessOutcome,
    Verdict,
)
from job_runner_agent.guard.workpath import PathRejected, WorkFolder, WorkPath

JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4),
    max_leaves=12,
)


def make_context(
    tmp_path: Path, payload: Mapping[str, Any], options: Mapping[str, Any] | None = None
) -> ExecutionContext:
    folder = WorkFolder.create(tmp_path / "work-root", "job-contract")
    return ExecutionContext(
        job_id="job-contract",
        job_type="type-a",
        payload=payload,
        timeout=timedelta(seconds=60),
        work=folder,
        source_dir=folder.path_of("src"),
        options=options or {},
    )


class ExecutorContract:
    def test_same_input_gives_same_plan(
        self, executor: Executor, valid_payloads: list[dict[str, Any]], tmp_path: Path
    ) -> None:
        for payload in valid_payloads:
            a = executor.prepare(make_context(tmp_path / "a", payload))
            b = executor.prepare(make_context(tmp_path / "b", payload))
            assert (a.tool_id, a.cwd, tuple(a.artifact_patterns), dict(a.extra_env)) == (
                b.tool_id,
                b.cwd,
                tuple(b.artifact_patterns),
                dict(b.extra_env),
            )
            assert [_text(x) for x in a.args] == [_text(x, "b") for x in b.args]

    def test_plans_pass_the_agent_validation(
        self, executor: Executor, valid_payloads: list[dict[str, Any]], tool_ids: set[str], tmp_path: Path
    ) -> None:
        for payload in valid_payloads:
            context = make_context(tmp_path, payload)
            plan = executor.prepare(context)
            assert plan.tool_id in tool_ids
            assert all(isinstance(arg, (Literal, WorkPath)) for arg in plan.args)
            context.work.resolve(plan.cwd)
            for pattern in plan.artifact_patterns:
                compile_pattern(pattern)

    def test_prepare_does_not_launch_processes_or_use_network(
        self, executor: Executor, valid_payloads: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("エグゼキュータはプロセスの起動・通信をしない")

        monkeypatch.setattr(subprocess, "Popen", forbidden)
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        for payload in valid_payloads:
            context = make_context(tmp_path, payload)
            executor.prepare(context)
            for exit_code in (0, 1, None):
                executor.interpret(context, ProcessOutcome(exit_code))

    def test_interpret_returns_a_verdict_for_every_exit_code(
        self, executor: Executor, valid_payloads: list[dict[str, Any]], tmp_path: Path
    ) -> None:
        context = make_context(tmp_path, valid_payloads[0])
        executor.prepare(context)
        for exit_code in (0, 1, 2, 255, -1, None):
            verdict = executor.interpret(context, ProcessOutcome(exit_code))
            assert isinstance(verdict, Verdict)
            assert verdict.summary is None or len(verdict.summary) <= 200
            if exit_code == 0:
                assert verdict.succeeded
            else:
                assert not verdict.succeeded and verdict.failure_reason is not None

    def test_invalid_payload_is_rejected(self, executor: Executor, tmp_path: Path) -> None:
        for payload in ({}, {"unknown": 1}, {"check": None}):
            with pytest.raises((ExecutorRejected, PathRejected)):
                executor.prepare(make_context(tmp_path, payload))

    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(payload=st.dictionaries(st.text(max_size=10), JSON, max_size=5))
    def test_any_payload_only_raises_rejections(
        self, executor: Executor, tmp_path: Path, payload: dict[str, Any]
    ) -> None:
        with contextlib.suppress(ExecutorRejected, PathRejected):  # 許される拒否
            executor.prepare(make_context(tmp_path / "h", payload))


def _text(arg: object, _salt: str = "") -> str:
    if isinstance(arg, Literal):
        return arg.value
    assert isinstance(arg, WorkPath)
    return arg.rel
