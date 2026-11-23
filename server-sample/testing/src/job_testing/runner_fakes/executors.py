"""偽のエグゼキュータ(004 T021。FR-012)。

`FakeExecutor` は、payload の `cmd` と `args` に従って、偽のツール(`tools/fake_tool.py`)を起動する計画を返す。
`args` の要素が文字列ならそのまま、`{"work": "<相対パス>"}` なら作業フォルダ内に検査して渡す(検査に落ちると
PathRejected)。
用途固有の語を使わない。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job_runner_agent.executor import (
    Arg,
    ExecutionContext,
    ExecutionPlan,
    ExecutorRejected,
    Literal,
    ProcessOutcome,
    Verdict,
    default_verdict,
)

FAKE_TOOL = str(Path(__file__).resolve().parent / "tools" / "fake_tool.py")
TOOL_ID = "py"


class FakeExecutor:
    """スリープ・出力・子プロセス・秘密の読み取り・パスの逸脱など、payload で振る舞いを選ぶ偽のエグゼキュータ。"""

    def prepare(self, ctx: ExecutionContext) -> ExecutionPlan:
        payload = ctx.payload
        cmd = payload.get("cmd")
        if not isinstance(cmd, str):
            raise ExecutorRejected
        args: list[Arg] = [Literal(FAKE_TOOL), Literal(cmd)]
        for item in payload.get("args", []):
            if isinstance(item, str):
                args.append(Literal(item))
            elif isinstance(item, dict) and isinstance(item.get("work"), str):
                args.append(ctx.work.resolve(item["work"]))
            else:
                raise ExecutorRejected
        return ExecutionPlan(
            tool_id=payload.get("tool_id", TOOL_ID),
            args=args,
            cwd=payload.get("cwd", "work"),
            artifact_patterns=list(payload.get("patterns", [])),
            extra_env=dict(payload.get("env", {})),
        )

    def interpret(self, ctx: ExecutionContext, outcome: ProcessOutcome) -> Verdict:
        verdict = default_verdict(outcome)
        summary = ctx.payload.get("summary")
        if isinstance(summary, str):
            return Verdict(verdict.succeeded, verdict.failure_reason, summary)
        return verdict


class RaisingExecutor:
    """prepare / interpret が予期しない例外を起こすエグゼキュータ(エージェントが停止しないことの検査)。"""

    def __init__(self, where: str = "prepare") -> None:
        self.where = where

    def prepare(self, ctx: ExecutionContext) -> ExecutionPlan:
        if self.where == "prepare":
            raise RuntimeError("SECRET-IN-EXCEPTION")
        return ExecutionPlan(tool_id=TOOL_ID, args=[Literal(FAKE_TOOL), Literal("echo"), Literal("x")])

    def interpret(self, ctx: ExecutionContext, outcome: ProcessOutcome) -> Verdict:
        raise RuntimeError("SECRET-IN-EXCEPTION")


def payload(cmd: str, *args: Any, **extra: Any) -> dict[str, Any]:
    return {"cmd": cmd, "args": list(args), **extra}
