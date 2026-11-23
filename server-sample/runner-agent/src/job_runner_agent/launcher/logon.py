"""LogonLauncher(prod。research.md R4)。ツール用の専用の低権限アカウントとして、外部ツールを起動する。

CreateProcessWithLogonW で、一時停止の状態で生成 → Job Object へ割り当て → 再開する。
環境ブロックは呼び出し元が組み立てた
完全なもの(親の環境を渡さない)。標準入力は閉じ、標準出力・標準エラーは別々のパイプで読む。
ツールのアカウントの資格は SecretSource から読む(形式: `ユーザー名:パスワード`。ユーザー名は `ドメイン\\名前`
または `名前`)。

**検証の状況**: この実装は、2 アカウントを構築した PC での検証(-m twoaccount。tasks T001、T071)が前提。
サービスの文脈(非対話・セッション 0)で、対象のツールを起動できるかは、スパイク(runner-agent/spikes/logon_spike.py)
で確認する。
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import os
import subprocess
from collections.abc import AsyncIterator, Mapping, Sequence
from ctypes import wintypes

from ..secret_source import SecretSource
from . import winapi
from .port import LaunchSpec

READ_SIZE = 65536
LOGON_WITH_PROFILE = 0x00000001
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
INFINITE = 0xFFFFFFFF
WAIT_TIMEOUT = 0x102


def build_environment_block(env: Mapping[str, str]) -> str:
    """CreateProcess の環境ブロック(`名前=値\\0 ... \\0`)。名前の順(大文字小文字を区別しない)に並べる。"""
    if any("\x00" in k or "\x00" in v or "=" in k or not k for k, v in env.items()):
        raise ValueError("環境変数の名前・値が不正")
    items = sorted(env.items(), key=lambda kv: kv[0].upper())
    return "".join(f"{k}={v}\x00" for k, v in items) + "\x00"


def build_command_line(exe: str, args: Sequence[str]) -> str:
    return subprocess.list2cmdline([exe, *args])


def split_account(secret: str) -> tuple[str, str | None, str]:
    """`ドメイン\\名前:パスワード` を (名前, ドメイン, パスワード) に分ける。"""
    account, separator, password = secret.partition(":")
    if not separator or not account or not password:
        raise ValueError("ツールのアカウントの資格の形式が不正")
    if "\\" in account:
        domain, _, name = account.partition("\\")
        return name, domain, password
    return account, ".", password


class _StartupInfo(ctypes.Structure):
    _fields_ = (
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    )


class _ProcessInformation(ctypes.Structure):
    _fields_ = (
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    )


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    )


def _create_pipe() -> tuple[int, int]:
    """(読み取り側の fd、書き込み側のハンドル)。書き込み側だけが子に継承される。"""
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreatePipe.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
    )
    kernel32.SetHandleInformation.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
    read, write = wintypes.HANDLE(), wintypes.HANDLE()
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
    if not kernel32.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(attributes), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel32.SetHandleInformation(read, HANDLE_FLAG_INHERIT, 0)  # 読み取り側は継承させない
    return msvcrt.open_osfhandle(int(read.value or 0), os.O_RDONLY), int(write.value or 0)


async def _read_fd(fd: int) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, fd, READ_SIZE)
            except OSError:
                return
            if not data:
                return
            yield data
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


class LogonRunningProcess:
    def __init__(self, process_handle: int, job: winapi.JobObject, out_fd: int, err_fd: int) -> None:
        self._handle = process_handle
        self._job = job
        self._out_fd, self._err_fd = out_fd, err_fd
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    @property
    def stdout(self) -> AsyncIterator[bytes]:
        return _read_fd(self._out_fd)

    @property
    def stderr(self) -> AsyncIterator[bytes]:
        return _read_fd(self._err_fd)

    async def wait(self) -> int | None:
        def block() -> int | None:
            self._kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            self._kernel32.WaitForSingleObject(self._handle, INFINITE)
            code = wintypes.DWORD()
            self._kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            if not self._kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
                return None
            return int(code.value)

        return await asyncio.get_running_loop().run_in_executor(None, block)

    async def terminate_tree(self, wait: float) -> bool:
        self._job.terminate()
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
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle(self._handle)


class LogonLauncher:
    def __init__(self, secrets: SecretSource, account_secret_name: str) -> None:
        self._secrets = secrets
        self._account_secret_name = account_secret_name

    async def launch(self, spec: LaunchSpec) -> LogonRunningProcess:
        return await asyncio.to_thread(self._launch, spec)

    def _launch(self, spec: LaunchSpec) -> LogonRunningProcess:
        if not winapi.IS_WINDOWS:
            raise OSError("Windows のみ")
        name, domain, password = split_account(self._secrets.get(self._account_secret_name).reveal())
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        create = advapi.CreateProcessWithLogonW
        create.argtypes = (
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.POINTER(_StartupInfo),
            ctypes.POINTER(_ProcessInformation),
        )
        create.restype = wintypes.BOOL
        out_fd, out_write = _create_pipe()
        err_fd, err_write = _create_pipe()
        nul = os.open(os.devnull, os.O_RDONLY)
        import msvcrt

        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(_StartupInfo)
        startup.dwFlags = STARTF_USESTDHANDLES
        startup.hStdInput = msvcrt.get_osfhandle(nul)
        startup.hStdOutput, startup.hStdError = out_write, err_write
        info = _ProcessInformation()
        command = ctypes.create_unicode_buffer(build_command_line(spec.exe, spec.args))
        block = build_environment_block(spec.env)
        environment = ctypes.create_unicode_buffer(block, len(block))
        job = winapi.JobObject(spec.memory_limit_bytes)
        try:
            ok = create(
                name,
                domain,
                password,
                LOGON_WITH_PROFILE,
                spec.exe,
                command,
                winapi.CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | winapi.CREATE_NO_WINDOW,
                ctypes.cast(environment, ctypes.c_void_p),
                spec.cwd,
                ctypes.byref(startup),
                ctypes.byref(info),
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
            job.assign(info.hProcess)
            winapi.resume_process(info.hProcess)
        except BaseException:
            job.terminate()
            job.close()
            os.close(out_fd)
            os.close(err_fd)
            raise
        finally:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            for handle in (out_write, err_write):
                kernel32.CloseHandle(handle)  # 子へ渡した書き込み側を、エージェント側では閉じる
            os.close(nul)
            if info.hThread:
                kernel32.CloseHandle(info.hThread)
            password = ""
        return LogonRunningProcess(info.hProcess, job, out_fd, err_fd)
