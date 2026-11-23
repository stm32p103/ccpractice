"""スパイク(tasks T001): 2 アカウント方式(research.md R4)が、対象の環境で成立するかを確かめる。

**これは、ツール用のアカウントを作った PC で、人が実行する検証用のスクリプト**。本体(job_runner_agent)から import
しない。
実行の前提:
- ツール用のローカルアカウント(例: svc-runner-tool)を作り、作業フォルダ(例: D:\\runner\\work\\spike)
だけに変更の権限を与える。
- エージェント用のアカウント(例: svc-runner-agent)で、このスクリプトを実行する(サービスの文脈で試すなら、WinSW
のサービスとして)。
- ツールのアカウントの資格を、環境変数 SPIKE_TOOL_ACCOUNT に `ユーザー名:パスワード` の形で与える(この実行の間だけ)。

    python -I runner-agent/spikes/logon_spike.py --work D:\\runner\\work\\spike --secret-file
    D:\\runner\\secret-outside.txt

検査する項目(すべて OK なら成立):
 1. ログオン付きの生成(CreateProcessWithLogonW)が、一時停止で成功し、Job Object へ割り当てて再開できる。
 2. 環境ブロックを空から渡せる(親の環境の変数が子に見えない)。
 3. ツールのアカウントが、作業フォルダ以外(--secret-file)を読めない。
 4. TerminateJobObject で、子・孫まで止まる。
 5. エージェントのプロセスの終了で、子が終了する(KILL_ON_JOB_CLOSE)。この項目は --crash で別に実行する。
結果は、specs/004-runner-agent/research.md の R4 に追記する。成立しない項目があれば、plan を改定して確認を得る。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_runner_agent.launcher.logon import LogonLauncher
from job_runner_agent.launcher.port import LaunchSpec
from job_runner_agent.secret_source import EnvSecretSource

CHILD = r"""
import json, os, subprocess, sys, time
secret_file = sys.argv[1]
try:
    open(secret_file, "rb").read(1); readable = True
except OSError:
    readable = False
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(json.dumps({"env": sorted(os.environ), "secret_readable": readable, "whoami": os.environ.get("USERNAME"),
"grandchild": grandchild.pid}), flush=True)
time.sleep(120)
"""


async def run(args: argparse.Namespace) -> int:
    launcher = LogonLauncher(EnvSecretSource(), "SPIKE_TOOL_ACCOUNT")
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    env = {"SystemRoot": os.environ.get("SYSTEMROOT", "C:\\Windows")}
    spec = LaunchSpec(args.python, ["-c", CHILD, args.secret_file], str(work), env)
    process = await launcher.launch(spec)
    first = b""
    async for data in process.stdout:
        first += data
        if b"\n" in first:
            break
    info = json.loads(first.decode().splitlines()[0])
    results = {
        "1_launch_and_resume": True,
        "2_empty_environment": "PARENT_DUMMY_SECRET" not in info["env"]
        and "PATH" not in {e.upper() for e in info["env"]},
        "3_secret_unreadable": info["secret_readable"] is False,
        "tool_account": info["whoami"],
    }
    if args.crash:
        print("エージェントを強制終了します。子(と孫)が終了していることを、別の端末で確認してください。")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        os._exit(1)
    stopped = await process.terminate_tree(5)
    results["4_terminate_tree"] = stopped and process.active_processes() == 0
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(v is True for k, v in results.items() if k[0].isdigit()) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", required=True)
    parser.add_argument(
        "--secret-file", required=True, help="作業フォルダの外にある、ツールのアカウントが読めないはずのファイル"
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--crash", action="store_true", help="項目 5: エージェントの強制終了で子が終了するか")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
