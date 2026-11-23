"""成果物の保存先のポート(contracts/ports.md「ArtifactStore」。research.md R11)。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from job_runner_protocol.messages import ArtifactReference


class ArtifactStoreError(Exception):
    """保存できない(容量・権限・通信)。メッセージに作業フォルダ・保存先のパスを含めない。"""


class ArtifactExists(ArtifactStoreError):
    """同じ (job_id, name) が既にある(上書きしない)。"""


class ArtifactStore(Protocol):
    async def put(self, job_id: str, name: str, source: Path) -> ArtifactReference:
        """source(作業フォルダ内の通常のファイル)を保存先へ書き、参照を返す。中途半端なファイルを残さない。"""
        ...

    async def purge_older_than(self, cutoff: datetime) -> int:
        """保持期間を過ぎたジョブの成果物を削除して、件数を返す。"""
        ...

    async def free_quota(self) -> int:
        """保存先の総容量の上限までの残り(バイト)。"""
        ...

    async def verify_writable(self) -> None:
        """書き込めることを確認する(起動時の自己検査)。書けなければ ArtifactStoreError。"""
        ...
