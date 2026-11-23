"""ソースの取得(contracts/ports.md「SourceFetcher」。research.md R12。FR-026)。

取得はエージェントが担当する。許可リストの検査と取得資格の扱いはエージェント(execution.py)が行い、ここは取得だけ。
実アダプタ(リモートの取得)は 005 が実装する。004 では、ポートと、開発・試験用の LocalDirectorySourceFetcher だけを持つ。
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Protocol

from job_runner_protocol.messages import SourceCredential

from .guard.workpath import PathRejected, WorkPath, check_relative


class SourceUnavailable(Exception):
    """取得できない。メッセージに資格・入力値を含めない。"""


class SourceFetcher(Protocol):
    async def fetch(
        self, source: str, revision: str | None, credential: SourceCredential | None, dest: WorkPath
    ) -> None:
        """revision に固定して dest へ取得する。dest の外へ書かない。履歴のメタデータ(.git など)を残さない。"""
        ...


_SKIP = shutil.ignore_patterns(".git", ".hg", ".svn")


class LocalDirectorySourceFetcher:
    """`<root>/<source>/<revision>`(なければ `<root>/<source>`)を dest へコピーする(dev のみ)。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    async def fetch(
        self, source: str, revision: str | None, credential: SourceCredential | None, dest: WorkPath
    ) -> None:
        try:
            source_parts = check_relative(source)
            revision_parts = check_relative(revision) if revision else ()
        except PathRejected as exc:
            raise SourceUnavailable("取得元の指定が不正") from exc
        base = self._root.joinpath(*source_parts)
        candidate = base.joinpath(*revision_parts) if revision_parts else base
        origin = candidate if candidate.is_dir() else base
        if not origin.is_dir() or (revision_parts and not candidate.is_dir()):
            raise SourceUnavailable("取得元が存在しない")
        if not origin.resolve().is_relative_to(self._root.resolve()):
            raise SourceUnavailable("取得元の指定が不正")
        await asyncio.to_thread(shutil.copytree, origin, dest.path, ignore=_SKIP, dirs_exist_ok=True, symlinks=False)
