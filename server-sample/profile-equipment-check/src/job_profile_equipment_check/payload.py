"""equipment-check の payload の形の検証(用途固有)。

形は次のとおり。解釈できない入力は ExecutorRejected(固定の語彙。入力値をメッセージに含めない)。

    {"check": "<チェックの名前>", "input": "<取得したソース内の相対パス(任意)>", "args": ["<追加の引数>", ...]}
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from job_runner_agent.executor import ExecutorRejected

_CHECK_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_ARGS = 16
MAX_ARG_LENGTH = 256
MAX_INPUT_LENGTH = 260


@dataclass(frozen=True)
class CheckRequest:
    check: str
    input: str | None
    args: tuple[str, ...]


def parse_payload(payload: Mapping[str, Any]) -> CheckRequest:
    check = payload.get("check")
    if not isinstance(check, str) or not _CHECK_NAME.match(check):
        raise ExecutorRejected
    raw_input = payload.get("input")
    if raw_input is not None and (not isinstance(raw_input, str) or not 0 < len(raw_input) <= MAX_INPUT_LENGTH):
        raise ExecutorRejected
    raw_args = payload.get("args", [])
    if not isinstance(raw_args, list) or len(raw_args) > MAX_ARGS:
        raise ExecutorRejected
    for arg in raw_args:
        if not isinstance(arg, str) or len(arg) > MAX_ARG_LENGTH or "\x00" in arg:
            raise ExecutorRejected
    unknown = set(payload) - {"check", "input", "args"}
    if unknown:
        raise ExecutorRejected
    return CheckRequest(check, raw_input, tuple(raw_args))
