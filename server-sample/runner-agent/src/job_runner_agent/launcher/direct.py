"""DirectLauncher(dev のみ。research.md R4)。エージェントと同じアカウントで直接起動する。

シェルを介さず、完全な環境ブロックと引数の配列で起動する。一時停止で生成 → Job Object へ割り当て → 再開する
(子孫を含めて停止できる。エージェントの終了で子孫も終了する)。標準入力は閉じる。
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator

from . import winapi
from .port import LaunchSpec

READ_SIZE = 65536


async def _iterate(stream: asyncio.StreamReader | None) -> AsyncIterator[bytes]:
    if stream is None:
        return
    while True:
        data = await stream.read(READ_SIZE)
        if not data:
            return
        yield data


class DirectRunningProcess:
    def __init__(self, process: asyncio.subprocess.Process, job: winapi.JobObject) -> None:
        self._process = process
        self._job = job

    @property
    def stdout(self) -> AsyncIterator[bytes]:
        return _iterate(self._process.stdout)

    @property
    def stderr(self) -> AsyncIterator[bytes]:
        return _iterate(self._process.stderr)

    async def wait(self) -> int | None:
        code = await self._process.wait()
        return code

    async def terminate_tree(self, wait: float) -> bool:
        self._job.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=wait)
        except TimeoutError:
            return False
        deadline = asyncio.get_running_loop().time() + wait
        while self._job.active_processes() > 0:
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.02)
        return True

    def active_processes(self) -> int:
        return self._job.active_processes()

    def close(self) -> None:
        self._job.close()


class DirectLauncher:
    async def launch(self, spec: LaunchSpec) -> DirectRunningProcess:
        job = winapi.JobObject(spec.memory_limit_bytes)
        try:
            process = await asyncio.create_subprocess_exec(
                spec.exe,
                *spec.args,
                cwd=spec.cwd,
                env=dict(spec.env),
                stdin=subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=winapi.CREATE_SUSPENDED | winapi.CREATE_NEW_PROCESS_GROUP | winapi.CREATE_NO_WINDOW,
            )
            popen = process._transport.get_extra_info("subprocess")  # type: ignore[attr-defined]
            handle = int(popen._handle)
            job.assign(handle)
            winapi.resume_process(handle)
        except BaseException:
            job.terminate()
            job.close()
            raise
        return DirectRunningProcess(process, job)
