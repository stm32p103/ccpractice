"""SharedFolderArtifactStore(research.md R11)。

ランナーごとに設定する「実行結果」フォルダ(ランナー自身の PC の共有フォルダ)の 1 か所だけに、`<job_id>\\<名前>`
として書く。
参照は UNC パス(`\\\\<ホスト>\\<共有名>\\<job_id>\\<名前>`)。アクセス権は作成・変更しない(本システムの範囲外)。
一時名で書いてから確定し、中途半端なファイルを残さない。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

from job_runner_protocol.messages import ArtifactReference
from job_runner_protocol.vocabulary import ArtifactKind

from ..settings import ArtifactStoreSettings
from .port import ArtifactExists, ArtifactStoreError

_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")
CHUNK = 1024 * 1024


def _safe(name: str) -> str:
    return _SAFE.sub("_", name)[:120] or "x"


class SharedFolderArtifactStore:
    def __init__(self, settings: ArtifactStoreSettings) -> None:
        if settings.shared_folder is None:
            raise ValueError("shared_folder の設定が必要")
        self._folder = settings.shared_folder
        self._root = Path(self._folder.local_path)
        self._quota = settings.store_quota_bytes

    async def put(self, job_id: str, name: str, source: Path) -> ArtifactReference:
        try:
            return await asyncio.to_thread(self._put, job_id, name, source)
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError("保存に失敗した") from exc

    def _put(self, job_id: str, name: str, source: Path) -> ArtifactReference:
        directory = self._root / _safe(job_id)
        target = directory / name
        if target.exists():
            raise ArtifactExists("既に存在する")
        if os.path.getsize(source) > self._free_quota():
            raise ArtifactStoreError("保存先の容量の上限に達した")
        directory.mkdir(parents=True, exist_ok=True)
        part = directory / f"{name}.part-{secrets.token_hex(4)}"
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as reader, part.open("wb") as writer:
                while block := reader.read(CHUNK):
                    digest.update(block)
                    size += len(block)
                    writer.write(block)
            os.replace(part, target)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        reference = f"\\\\{self._folder.unc_host}\\{self._folder.share_name}\\{_safe(job_id)}\\{name}"
        return ArtifactReference(name, ArtifactKind.UNC, reference, size, digest.hexdigest())

    async def purge_older_than(self, cutoff: datetime) -> int:
        return await asyncio.to_thread(self._purge, cutoff)

    def _purge(self, cutoff: datetime) -> int:
        removed = 0
        if not self._root.is_dir():
            return 0
        for entry in self._root.iterdir():
            if entry.is_dir() and datetime.fromtimestamp(entry.stat().st_mtime, UTC) < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        return removed

    async def free_quota(self) -> int:
        return await asyncio.to_thread(self._free_quota)

    def _free_quota(self) -> int:
        used = 0
        if self._root.is_dir():
            for directory, _subdirs, files in os.walk(self._root):
                for file_name in files:
                    try:
                        used += (Path(directory) / file_name).stat().st_size
                    except OSError:
                        continue
        return max(0, self._quota - used)

    async def verify_writable(self) -> None:
        def check() -> None:
            self._root.mkdir(parents=True, exist_ok=True)
            probe = self._root / f".write-check-{secrets.token_hex(4)}"
            probe.write_bytes(b"x")
            probe.unlink()

        try:
            await asyncio.to_thread(check)
        except OSError as exc:
            raise ArtifactStoreError("実行結果フォルダに書き込めない") from exc
