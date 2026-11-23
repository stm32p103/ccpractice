"""ランナーエージェントの起動の入口(Windows サービスから起動される)。

    python -m job_runner_service --config <agent.toml>          # 起動
    python -m job_runner_service --config <agent.toml> --check  # 設定と組み立ての検証だけ(ドライラン。通信しない)

停止の信号(Ctrl+C、Ctrl+Break、サービスの停止)で、実行中のジョブを止めて(agent_shutdown)、後始末をして終了する。
prod では、起動前の自己検査(ファイアウォールの規則、状態フォルダの ACL)に通らなければ、起動しない。
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from collections.abc import Sequence

from job_runner_agent.agent import RunnerAgent
from job_runner_agent.settings import SettingsError

from .selfcheck import run_selfcheck
from .settings import load_settings
from .wiring import WiringError, build_context


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job_runner_service")
    parser.add_argument("--config", required=True, help="agent.toml のパス")
    parser.add_argument("--check", action="store_true", help="設定と組み立てを検証して終了する")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        failures = run_selfcheck(settings)
    except (SettingsError, OSError, ValueError) as exc:
        print(
            f"設定の検証に失敗: {type(exc).__name__}: {exc}", file=sys.stderr
        )  # 値を含まない(SettingsError は場所と理由だけ)
        return 2
    if failures:
        for failure in failures:
            print(f"起動前の検査に失敗: {failure.item}: {failure.reason}", file=sys.stderr)
        return 3
    try:
        context = build_context(settings)
    except (WiringError, KeyError, ValueError) as exc:
        print(f"組み立てに失敗: {type(exc).__name__}", file=sys.stderr)
        return 2
    if args.check:
        print("設定と組み立ての検証に成功")
        return 0
    return asyncio.run(_serve(RunnerAgent(context)))


async def _serve(agent: RunnerAgent) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGBREAK", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows の Proactor ループでは未対応
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        await agent.run(stop)
    finally:
        await agent.ctx.client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
