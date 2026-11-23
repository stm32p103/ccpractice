"""FakeExecutor が ExecutorContract を通る(T064)。"""

from __future__ import annotations

from typing import Any

import pytest

from job_testing.contracts.executor import ExecutorContract
from job_testing.runner_fakes.executors import FakeExecutor, payload


@pytest.fixture
def executor() -> FakeExecutor:
    return FakeExecutor()


@pytest.fixture
def valid_payloads() -> list[dict[str, Any]]:
    return [
        payload("echo", "hello"),
        payload("sleep", "1", patterns=["work\\*.txt"]),
        payload("cat", {"work": "src\\a.txt"}),
    ]


@pytest.fixture
def tool_ids() -> set[str]:
    return {"py"}


class TestFakeExecutor(ExecutorContract):
    pass
