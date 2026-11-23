"""プロセスの生存確認の試験用の部品(Windows。004)。"""

from __future__ import annotations

import asyncio
import ctypes
import time
from ctypes import wintypes
from pathlib import Path

STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def pid_alive(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def read_pids(pid_file: Path) -> list[int]:
    pids = []
    for path in (pid_file, Path(str(pid_file) + ".g")):
        if path.exists():
            pids.append(int(path.read_text()))
    return pids


async def wait_pids(pid_file: Path, count: int = 2, timeout: float = 15.0) -> list[int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = read_pids(pid_file)
        if len(pids) >= count:
            return pids
        await asyncio.sleep(0.05)
    raise TimeoutError("子・孫のプロセスが起動しなかった")
