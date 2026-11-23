"""エグゼキュータのポートと値(data-model.md §1.2。contracts/ports.md「Executor」)。

エグゼキュータは、ジョブの payload を解釈して「実行計画」を返すだけで、プロセスを起動しない。
ExecutionContext に、資格・環境・コアのクライアントを含めない。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from job_runner_protocol.vocabulary import FailureReason

from .guard.workpath import WorkFolder, WorkPath


class ExecutorRejected(Exception):
    """payload を解釈できない・受け付けられない。reason_code は固定の語彙(メッセージに入力値を含めない)。"""

    def __init__(self, reason_code: str = "input_rejected") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class Literal:
    """そのまま渡す引数。"""

    value: str


Arg = Literal | WorkPath


@dataclass(frozen=True)
class ExecutionContext:
    job_id: str
    job_type: str
    payload: Mapping[str, Any]
    timeout: timedelta
    work: WorkFolder
    source_dir: WorkPath | None = None
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPlan:
    tool_id: str
    args: Sequence[Arg] = ()
    cwd: str = "work"
    """作業フォルダ直下からの相対パス(WorkPath と同じ検査を通る)。"""
    artifact_patterns: Sequence[str] = ()
    extra_env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessOutcome:
    exit_code: int | None
    stopped_by: str = "none"
    """none、abort、timeout、shutdown、lease_lost のいずれか。"""
    duration_seconds: float = 0.0
    output_truncated: bool = False


@dataclass(frozen=True)
class Verdict:
    succeeded: bool
    failure_reason: FailureReason | None = None
    summary: str | None = None


class Executor(Protocol):
    def prepare(self, ctx: ExecutionContext) -> ExecutionPlan: ...

    def interpret(self, ctx: ExecutionContext, outcome: ProcessOutcome) -> Verdict: ...


def default_verdict(outcome: ProcessOutcome) -> Verdict:
    """既定の解釈: 終了コード 0 なら成功。"""
    if outcome.exit_code == 0:
        return Verdict(True)
    return Verdict(False, FailureReason.TOOL_FAILED)
