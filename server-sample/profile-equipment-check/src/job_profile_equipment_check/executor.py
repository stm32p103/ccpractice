"""equipment-check のエグゼキュータ(最初の用途。FR-022)。

チェックツールの起動の組み立て(引数・作業ディレクトリ・成果物のパターン)と、結果の解釈だけを持つ。
プロセスを起動しない・通信しない(計画を返すだけ)。ツールの実体は、設定の tool_id(options の `tool_id`。既定
`check-tool`)で
エージェントの登録簿から解決される。

ツールの契約(このエグゼキュータの前提):
- 起動: `<tool> --check <名前> [--input <src 内のパス>] --report <work\\report.json> [追加の引数...]`(
作業ディレクトリは work\\)
- 終了コード: 0 = すべて合格、1 = 不合格のチェックあり、その他 = ツールの異常
- report.json(任意): {"passed": <整数>, "total": <整数>} を含む JSON(64 KiB まで)
"""

from __future__ import annotations

import json

from job_runner_agent.executor import (
    ExecutionContext,
    ExecutionPlan,
    Literal,
    ProcessOutcome,
    Verdict,
)
from job_runner_protocol.vocabulary import FailureReason

from .payload import parse_payload

REPORT_PATH = "work\\report.json"
DEFAULT_TOOL_ID = "check-tool"
MAX_REPORT_BYTES = 64 * 1024


class EquipmentCheckExecutor:
    def prepare(self, ctx: ExecutionContext) -> ExecutionPlan:
        request = parse_payload(ctx.payload)
        args: list[Literal | object] = [Literal("--check"), Literal(request.check)]
        if request.input is not None:
            # 取得したソースの中のパス。作業フォルダ外・リンクを指す入力は、ここで検査に落ちる(
            # エージェントが拒否として扱う)
            args += [Literal("--input"), ctx.work.resolve_under("src", request.input)]
        args += [Literal("--report"), ctx.work.resolve(REPORT_PATH)]
        args += [Literal(extra) for extra in request.args]
        tool_id = ctx.options.get("tool_id", DEFAULT_TOOL_ID)
        return ExecutionPlan(
            tool_id=str(tool_id),
            args=tuple(args),  # type: ignore[arg-type]
            cwd="work",
            artifact_patterns=("work\\report.json", "work\\*.log"),
        )

    def interpret(self, ctx: ExecutionContext, outcome: ProcessOutcome) -> Verdict:
        summary = self._report_summary(ctx)
        if outcome.exit_code == 0:
            return Verdict(True, None, summary)
        if outcome.exit_code == 1:
            return Verdict(False, FailureReason.TOOL_FAILED, summary or "チェックに不合格")
        return Verdict(False, FailureReason.TOOL_FAILED, "ツールの異常終了")

    @staticmethod
    def _report_summary(ctx: ExecutionContext) -> str | None:
        try:
            path = ctx.work.resolve(REPORT_PATH).path
            if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            passed, total = data["passed"], data["total"]
            if (
                isinstance(passed, bool)
                or isinstance(total, bool)
                or not isinstance(passed, int)
                or not isinstance(total, int)
            ):
                return None
            return f"{passed}/{total} 合格"
        except (OSError, ValueError, KeyError, TypeError):
            return None
