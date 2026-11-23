"""ArtifactStore の契約テスト(004 contracts/ports.md「ArtifactStore」)。

使い方: `store`(ArtifactStore)、`read_stored(reference) -> bytes`(保存した内容を参照から読む関数)、
`age_job(job_id, days)`(ジョブの成果物を古くする関数)を定義して、このクラスを継承する。
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_runner_agent.artifacts.port import ArtifactExists, ArtifactStore, ArtifactStoreError
from job_runner_protocol.messages import ArtifactReference


def make_file(tmp_path: Path, content: bytes, name: str = "src.bin") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


class ArtifactStoreContract:
    def test_content_hash_and_reference_form(
        self, store: ArtifactStore, read_stored: Callable[[ArtifactReference], bytes], tmp_path: Path
    ) -> None:
        content = b"hello artifact\n" * 100
        ref = asyncio.run(store.put("job-1", "report.txt", make_file(tmp_path, content)))
        assert ref.name == "report.txt" and ref.size_bytes == len(content)
        assert ref.sha256 == hashlib.sha256(content).hexdigest()
        assert ref.kind.value in ("unc", "url")  # 参照の形は ArtifactReference が検査済み
        assert read_stored(ref) == content
        # 作業フォルダ・ローカルのパスを参照に含めない
        assert str(tmp_path) not in ref.reference

    def test_existing_artifact_is_never_overwritten(self, store: ArtifactStore, tmp_path: Path) -> None:
        asyncio.run(store.put("job-1", "a.txt", make_file(tmp_path, b"first")))
        with pytest.raises(ArtifactExists):
            asyncio.run(store.put("job-1", "a.txt", make_file(tmp_path, b"second")))

    def test_same_name_in_different_jobs_is_allowed(
        self, store: ArtifactStore, read_stored: Callable[[ArtifactReference], bytes], tmp_path: Path
    ) -> None:
        a = asyncio.run(store.put("job-1", "a.txt", make_file(tmp_path, b"one")))
        b = asyncio.run(store.put("job-2", "a.txt", make_file(tmp_path, b"two")))
        assert read_stored(a) == b"one" and read_stored(b) == b"two" and a.reference != b.reference

    def test_no_partial_files_are_left_on_failure(self, store: ArtifactStore, tmp_path: Path) -> None:
        with pytest.raises(ArtifactStoreError):
            asyncio.run(store.put("job-1", "x.txt", tmp_path / "does-not-exist"))
        asyncio.run(store.put("job-1", "x.txt", make_file(tmp_path, b"ok")))  # 失敗の後も同じ名前で保存できる

    def test_purge_older_than_removes_only_old_jobs(
        self, store: ArtifactStore, age_job: Callable[[str, int], None], tmp_path: Path
    ) -> None:
        asyncio.run(store.put("old-job", "a.txt", make_file(tmp_path, b"old")))
        asyncio.run(store.put("new-job", "a.txt", make_file(tmp_path, b"new")))
        age_job("old-job", 40)
        removed = asyncio.run(store.purge_older_than(datetime.now(UTC) - timedelta(days=30)))
        assert removed == 1
        asyncio.run(store.put("old-job", "a.txt", make_file(tmp_path, b"again")))  # 削除されたので、再度保存できる
        with pytest.raises(ArtifactExists):
            asyncio.run(store.put("new-job", "a.txt", make_file(tmp_path, b"x")))

    def test_verify_writable_succeeds(self, store: ArtifactStore) -> None:
        asyncio.run(store.verify_writable())

    def test_free_quota_decreases_with_stored_bytes(self, store: ArtifactStore, tmp_path: Path) -> None:
        before = asyncio.run(store.free_quota())
        asyncio.run(store.put("job-q", "big.bin", make_file(tmp_path, b"x" * 1000)))
        assert asyncio.run(store.free_quota()) == before - 1000
