"""プロセスの起動と停止のポート(contracts/ports.md「ProcessLauncher」)。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LaunchSpec:
    """exe は tool_id から解決した絶対パス、args は解決済みの引数、env は完全な環境ブロック。"""

    exe: str
    args: Sequence[str]
    cwd: str
    env: Mapping[str, str]
    memory_limit_bytes: int | None = None


class RunningProcess(Protocol):
    @property
    def stdout(self) -> AsyncIterator[bytes]: ...

    @property
    def stderr(self) -> AsyncIterator[bytes]: ...

    async def wait(self) -> int | None:
        """終了コード。強制終了などで得られなければ None。"""
        ...

    async def terminate_tree(self, wait: float) -> bool:
        """起動したプロセスと子孫をすべて終了させる。残りがなければ真。"""
        ...

    def active_processes(self) -> int:
        """まだ動いているプロセスの数(子孫を含む)。"""
        ...


class ProcessLauncher(Protocol):
    async def launch(self, spec: LaunchSpec) -> RunningProcess: ...
