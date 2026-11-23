"""US6-2・V38: ツール用の別アカウントで実行する(-m twoaccount。2 アカウントを構築した PC のみ)。

環境変数 JOB_TEST_TOOL_ACCOUNT(`ユーザー名:パスワード`)と JOB_TEST_SECRET_FILE(
ツールのアカウントが読めないはずのファイル)、
JOB_TEST_WORK_ROOT(ツールのアカウントが書き込める作業フォルダの親)がある環境でだけ実行する。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from job_runner_agent.launcher.logon import LogonLauncher
from job_runner_agent.launcher.port import LaunchSpec
from job_runner_agent.secret_source import EnvSecretSource
from job_testing.contracts.process_launcher import FAKE_TOOL, ProcessLauncherContract, collect

pytestmark = [
    pytest.mark.twoaccount,
    pytest.mark.skipif(
        not all(os.environ.get(k) for k in ("JOB_TEST_TOOL_ACCOUNT", "JOB_TEST_SECRET_FILE", "JOB_TEST_WORK_ROOT")),
        reason="2 アカウントの試験の環境がない",
    ),
]


@pytest.fixture
def launcher() -> LogonLauncher:
    return LogonLauncher(EnvSecretSource({"TOOL_ACCOUNT": os.environ["JOB_TEST_TOOL_ACCOUNT"]}), "TOOL_ACCOUNT")


@pytest.fixture
def python_exe() -> str:
    return sys.executable


@pytest.fixture
def workdir(tmp_path: Path) -> str:
    folder = Path(os.environ["JOB_TEST_WORK_ROOT"]) / f"twoaccount-{os.getpid()}"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


class TestLogonLauncher(ProcessLauncherContract):
    pass


def test_us6_2_tool_account_cannot_read_outside_the_work_folder(launcher: LogonLauncher, workdir: str) -> None:
    secret_file = os.environ["JOB_TEST_SECRET_FILE"]

    async def go() -> str:
        spec = LaunchSpec(
            sys.executable,
            [str(FAKE_TOOL), "read-secrets", secret_file, "NO_SUCH_VAR", "out.txt"],
            workdir,
            {"SystemRoot": os.environ.get("SYSTEMROOT", "C:\\Windows")},
        )
        return (await collect(await launcher.launch(spec)))[0]

    out = asyncio.run(go())
    assert "file=<unreadable>" in out  # ダミーの秘密(ファイルの内容)が出力に現れない


def test_tool_runs_as_a_different_account(launcher: LogonLauncher, workdir: str) -> None:
    async def go() -> dict[str, str]:
        spec = LaunchSpec(
            sys.executable,
            [str(FAKE_TOOL), "env"],
            workdir,
            {"SystemRoot": os.environ.get("SYSTEMROOT", "C:\\Windows")},
        )
        return json.loads((await collect(await launcher.launch(spec)))[0])

    seen = asyncio.run(go())
    tool_user = os.environ["JOB_TEST_TOOL_ACCOUNT"].split(":", 1)[0].split("\\")[-1].lower()
    assert (
        seen.get("USERNAME", "").lower() in ("", tool_user)
        or seen.get("USERNAME", "").lower() != os.environ.get("USERNAME", "").lower()
    )
