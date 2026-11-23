"""ProcessLauncher の契約テスト(004 contracts/ports.md「ProcessLauncher」)。

使い方: `launcher`(ProcessLauncher)と `python_exe`(偽のツールを動かす実行ファイル)と `workdir`(作業ディレクトリ)の
フィクスチャを定義して、このクラスを継承する。実プロセスを起動するため `-m windows` で実行する。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from job_runner_agent.launcher.port import LaunchSpec, ProcessLauncher, RunningProcess

FAKE_TOOL = Path(__file__).resolve().parents[1] / "runner_fakes" / "tools" / "fake_tool.py"
SYSTEM_ENV = {"SystemRoot": os.environ.get("SYSTEMROOT", "C:\\Windows")}


def spec(python_exe: str, workdir: str, *tool_args: str, env: dict[str, str] | None = None) -> LaunchSpec:
    return LaunchSpec(python_exe, [str(FAKE_TOOL), *tool_args], workdir, {**SYSTEM_ENV, **(env or {})})


async def collect(process: RunningProcess) -> tuple[str, str, int | None]:
    async def read(stream: object) -> str:
        parts: list[bytes] = []
        async for data in stream:  # type: ignore[attr-defined]
            parts.append(data)
        return b"".join(parts).decode("utf-8", errors="replace")

    out, err = await asyncio.gather(read(process.stdout), read(process.stderr))
    return out, err, await process.wait()


class ProcessLauncherContract:
    def test_runs_and_collects_output_and_exit_code(
        self, launcher: ProcessLauncher, python_exe: str, workdir: str
    ) -> None:
        async def go() -> tuple[str, str, int | None]:
            process = await launcher.launch(spec(python_exe, workdir, "echo", "hello", "world"))
            return await collect(process)

        out, err, code = asyncio.run(go())
        assert out.strip() == "hello world" and code == 0 and err == ""

    def test_exit_code_and_stderr(self, launcher: ProcessLauncher, python_exe: str, workdir: str) -> None:
        async def go() -> tuple[str, str, int | None]:
            return await collect(await launcher.launch(spec(python_exe, workdir, "exit", "3")))

        assert asyncio.run(go())[2] == 3

        async def err() -> tuple[str, str, int | None]:
            return await collect(await launcher.launch(spec(python_exe, workdir, "err", "oops")))

        assert asyncio.run(err())[1].strip() == "oops"

    def test_environment_is_not_inherited(self, launcher: ProcessLauncher, python_exe: str, workdir: str) -> None:
        os.environ["PARENT_DUMMY_SECRET"] = "dummy-secret-value"
        try:

            async def go() -> str:
                process = await launcher.launch(spec(python_exe, workdir, "env", env={"ONLY_THIS": "1"}))
                return (await collect(process))[0]

            out = asyncio.run(go())
        finally:
            del os.environ["PARENT_DUMMY_SECRET"]
        seen = {k.upper() for k in json.loads(out)}
        assert "ONLY_THIS" in seen and "SYSTEMROOT" in seen
        assert "PARENT_DUMMY_SECRET" not in seen and "PATH" not in seen and "USERPROFILE" not in seen

    def test_special_characters_in_args_are_passed_verbatim(
        self, launcher: ProcessLauncher, python_exe: str, workdir: str
    ) -> None:
        args = ["a b", 'say "hi"', "x & y", "%PATH%", "$(whoami)", "a;b", "日本語", "", "back\\slash\\"]

        async def go() -> str:
            return (await collect(await launcher.launch(spec(python_exe, workdir, "args", *args))))[0]

        assert json.loads(asyncio.run(go())) == args

    def test_working_directory(self, launcher: ProcessLauncher, python_exe: str, workdir: str) -> None:
        async def go() -> str:
            return (await collect(await launcher.launch(spec(python_exe, workdir, "cwd"))))[0].strip()

        assert Path(asyncio.run(go())).resolve() == Path(workdir).resolve()

    def test_terminate_tree_stops_children_and_grandchildren(
        self, launcher: ProcessLauncher, python_exe: str, workdir: str
    ) -> None:
        pid_file = Path(workdir) / "pids"

        async def go() -> tuple[bool, int]:
            process = await launcher.launch(spec(python_exe, workdir, "spawn-child", "60", str(pid_file)))
            for _ in range(100):  # 孫が起動するまで待つ
                if Path(str(pid_file) + ".g").exists():
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.5)
            alive_before = process.active_processes()
            stopped = await process.terminate_tree(5)
            return stopped, alive_before

        stopped, alive_before = asyncio.run(go())
        assert alive_before >= 3  # 親・子・孫(・孫の孫)
        assert stopped

    def test_stopped_process_has_no_active_processes(
        self, launcher: ProcessLauncher, python_exe: str, workdir: str
    ) -> None:
        async def go() -> int:
            process = await launcher.launch(spec(python_exe, workdir, "sleep", "30"))
            await process.terminate_tree(5)
            return process.active_processes()

        assert asyncio.run(go()) == 0

    def test_missing_executable_fails_to_launch(self, launcher: ProcessLauncher, workdir: str) -> None:
        async def go() -> None:
            await launcher.launch(LaunchSpec("C:\\no\\such\\tool.exe", [], workdir, SYSTEM_ENV))

        with pytest.raises(OSError):
            asyncio.run(go())


PYTHON_EXE = sys.executable
