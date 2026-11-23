"""ツールからエージェントへのランナーの異常の申告(research.md R9。FR-023)。

ツールは、作業フォルダ内の `signal\\` に、決まった名前のファイルを書く: `fault.txt`(異常。UTF-8、1〜200 文字、
改行・制御文字なし)、
`recovered`(回復。空でよい)。エージェントだけがコア API へ送る(ツールから PC の外へは送らない)。
002 の規則(長さ・文字種)に違反する内容は送らず、監査に型だけを記録する(内容は記録しない)。
"""

from __future__ import annotations

from pathlib import Path

from .core_client import CoreClient, CoreRejected, CoreUnavailable
from .guard.fs_win import is_reparse_point
from .journal import AgentJournal

MAX_DESCRIPTION = 200
READ_LIMIT = 4096


def validate_description(raw: bytes) -> str | None:
    """検査に通れば説明の文字列、通らなければ None。"""
    try:
        text = raw[:READ_LIMIT].decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.strip()
    if not 1 <= len(text) <= MAX_DESCRIPTION:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        return None
    return text


class SignalWatcher:
    def __init__(self, signal_dir: Path, client: CoreClient, journal: AgentJournal, job_id: str) -> None:
        self._dir = signal_dir
        self._client = client
        self._journal = journal
        self._job_id = job_id

    async def poll(self) -> None:
        """1 回確認する。送れなかった(到達しない)ファイルは残して、次の確認で再度試す。"""
        await self._handle_fault()
        await self._handle_recovered()

    async def _handle_fault(self) -> None:
        path = self._dir / "fault.txt"
        if not path.exists():
            return
        if is_reparse_point(path):
            self._journal.audit("fault_signal_rejected", self._job_id, reason="reparse_point")
            path.unlink(missing_ok=True)
            return
        try:
            raw = path.read_bytes()
        except OSError:
            return  # 書き込み中などは、次の確認で読む
        text = validate_description(raw)
        if text is None:
            self._journal.audit("fault_signal_rejected", self._job_id, reason="invalid_content")
            path.unlink(missing_ok=True)
            return
        try:
            await self._client.report_fault(text)
        except CoreUnavailable:
            return
        except CoreRejected as rejection:
            self._journal.audit("fault_signal_rejected", self._job_id, reason="core_rejected", status=rejection.status)
        path.unlink(missing_ok=True)

    async def _handle_recovered(self) -> None:
        path = self._dir / "recovered"
        if not path.exists():
            return
        if is_reparse_point(path):
            path.unlink(missing_ok=True)
            return
        try:
            await self._client.report_recovered()
        except CoreUnavailable:
            return
        except CoreRejected as rejection:
            self._journal.audit("fault_signal_rejected", self._job_id, reason="core_rejected", status=rejection.status)
        path.unlink(missing_ok=True)
