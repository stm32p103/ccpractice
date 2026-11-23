"""JobLogStore の契約テスト(004 contracts/ports.md「JobLogStore」)。

使い方: `log_store` フィクスチャ(空の状態から始まる JobLogStore)を定義して、このクラスを継承する。
core-persistence(実アダプタ)も同じクラスを継承して実行する。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_core.job.application.ports import JobLogStore
from job_core.job.domain.errors import LogQuotaExceeded, LogSeqConflict
from job_core.job.domain.output import ArtifactKind, JobArtifactRef, JobLogChunk, LogStream
from job_core.shared.ids import JobId

AT = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)
J1 = JobId("j1")
J2 = JobId("j2")
BIG = 10_000_000


def chunk(seq: int, text: str = "x", stream: LogStream = LogStream.STDOUT) -> JobLogChunk:
    return JobLogChunk(seq=seq, stream=stream, text=text)


class JobLogStoreContract:
    def test_append_and_read_in_seq_order(self, log_store: JobLogStore) -> None:
        for seq in (1, 0, 2):  # 順不同でも受理する
            log_store.append(J1, chunk(seq, f"t{seq}"), AT, BIG)
        assert [c.seq for c in log_store.read(J1, -1, 10)] == [0, 1, 2]
        assert [c.text for c in log_store.read(J1, 0, 10)] == ["t1", "t2"]
        assert [c.seq for c in log_store.read(J1, -1, 2)] == [0, 1]

    def test_same_chunk_is_idempotent(self, log_store: JobLogStore) -> None:
        first = log_store.append(J1, chunk(0, "a"), AT, BIG)
        again = log_store.append(J1, chunk(0, "a"), AT, BIG)
        assert not first.duplicate
        assert again.duplicate
        assert len(log_store.read(J1, -1, 10)) == 1
        assert log_store.size(J1) == 1

    def test_different_content_for_same_seq_conflicts(self, log_store: JobLogStore) -> None:
        log_store.append(J1, chunk(0, "a"), AT, BIG)
        with pytest.raises(LogSeqConflict):
            log_store.append(J1, chunk(0, "b"), AT, BIG)
        with pytest.raises(LogSeqConflict):
            log_store.append(J1, chunk(0, "a", LogStream.STDERR), AT, BIG)

    def test_stored_up_to_seq_is_contiguous(self, log_store: JobLogStore) -> None:
        assert log_store.append(J1, chunk(1), AT, BIG).stored_up_to_seq == -1
        assert log_store.append(J1, chunk(0), AT, BIG).stored_up_to_seq == 1
        assert log_store.append(J1, chunk(3), AT, BIG).stored_up_to_seq == 1

    def test_quota_is_total_chars_per_job_and_rejected_chunk_is_not_stored(self, log_store: JobLogStore) -> None:
        log_store.append(J1, chunk(0, "a" * 6), AT, 10)
        with pytest.raises(LogQuotaExceeded):
            log_store.append(J1, chunk(1, "b" * 5), AT, 10)
        assert log_store.size(J1) == 6
        log_store.append(J2, chunk(0, "c" * 10), AT, 10)  # 別のジョブは別の枠
        log_store.append(J1, chunk(0, "a" * 6), AT, 10)  # 再送は上限の検査より先に冪等と判定される

    def test_purge_removes_logs_and_artifacts_of_the_job_only(self, log_store: JobLogStore) -> None:
        log_store.append(J1, chunk(0), AT, BIG)
        log_store.append(J2, chunk(0), AT, BIG)
        log_store.save_artifacts(J1, [artifact("a.txt")])
        assert log_store.purge(J1) >= 1
        assert log_store.read(J1, -1, 10) == []
        assert log_store.list_artifacts(J1) == []
        assert len(log_store.read(J2, -1, 10)) == 1

    def test_artifacts_roundtrip_keep_order(self, log_store: JobLogStore) -> None:
        refs = [artifact("b.txt"), artifact("a.txt")]
        log_store.save_artifacts(J1, refs)
        assert log_store.list_artifacts(J1) == refs
        assert log_store.list_artifacts(J2) == []

    def test_stored_chunks_have_receive_time(self, log_store: JobLogStore) -> None:
        log_store.append(J1, chunk(0), AT, BIG)
        assert log_store.read(J1, -1, 1)[0].received_at == AT


def artifact(name: str) -> JobArtifactRef:
    return JobArtifactRef(name, ArtifactKind.UNC, f"\\\\host\\share\\j1\\{name}", 3, "a" * 64)
