"""JobLogStore の SQLAlchemy 実装(contracts/ports.md「JobLogStore」)。

ジョブの UoW とは独立したトランザクションで確定する。(job_id, seq) は主キー。同じ内容の再送は冪等、異なる内容は
LogSeqConflict。
総量(文字数)の上限は、同じジョブについて助言ロックを取ってから集計して判定する(同時の追加で超過しない)。
**検証の状況**: PostgreSQL がある環境で `-m postgres` の契約テスト(JobLogStoreContract)を実行して確認する。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from job_core.job.application.ports import AppendResult
from job_core.job.domain.errors import LogQuotaExceeded, LogSeqConflict
from job_core.job.domain.output import ArtifactKind, JobArtifactRef, JobLogChunk, LogStream, StoredLogChunk
from job_core.shared.ids import JobId

from ..models import job_artifacts, job_log_chunks


class SqlJobLogStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, job_id: JobId, chunk: JobLogChunk, at: datetime, quota_chars: int) -> AppendResult:
        t = job_log_chunks.c
        with self._engine.begin() as conn:
            conn.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(sa.literal(str(job_id))))))
            existing = conn.execute(sa.select(t.stream, t.text).where(t.job_id == job_id, t.seq == chunk.seq)).first()
            if existing is not None:
                if (existing.stream, existing.text) != (chunk.stream.value, chunk.text):
                    raise LogSeqConflict(job_id, chunk.seq)
                return AppendResult(True, self._contiguous(conn, job_id))
            used = conn.execute(
                sa.select(sa.func.coalesce(sa.func.sum(t.chars), 0)).where(t.job_id == job_id)
            ).scalar_one()
            if int(used) + len(chunk.text) > quota_chars:
                raise LogQuotaExceeded(job_id)
            conn.execute(
                sa.insert(job_log_chunks).values(
                    job_id=job_id,
                    seq=chunk.seq,
                    stream=chunk.stream.value,
                    text=chunk.text,
                    chars=len(chunk.text),
                    received_at=at,
                )
            )
            return AppendResult(False, self._contiguous(conn, job_id))

    @staticmethod
    def _contiguous(conn: Connection, job_id: JobId) -> int:
        t = job_log_chunks.c
        seqs = [row.seq for row in conn.execute(sa.select(t.seq).where(t.job_id == job_id).order_by(t.seq))]
        last = -1
        for seq in seqs:
            if seq != last + 1:
                break
            last = seq
        return last

    def read(self, job_id: JobId, after_seq: int, limit: int) -> list[StoredLogChunk]:
        t = job_log_chunks.c
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(t.seq, t.stream, t.text, t.received_at)
                .where(t.job_id == job_id, t.seq > after_seq)
                .order_by(t.seq)
                .limit(limit)
            ).all()
        return [StoredLogChunk(r.seq, LogStream(r.stream), r.text, r.received_at) for r in rows]

    def size(self, job_id: JobId) -> int:
        t = job_log_chunks.c
        with self._engine.connect() as conn:
            total = conn.execute(sa.select(sa.func.coalesce(sa.func.sum(t.chars), 0)).where(t.job_id == job_id))
            return int(total.scalar_one())

    def purge(self, job_id: JobId) -> int:
        with self._engine.begin() as conn:
            logs = conn.execute(sa.delete(job_log_chunks).where(job_log_chunks.c.job_id == job_id)).rowcount
            refs = conn.execute(sa.delete(job_artifacts).where(job_artifacts.c.job_id == job_id)).rowcount
        return int(logs + refs)

    def save_artifacts(self, job_id: JobId, artifacts: Iterable[JobArtifactRef]) -> None:
        rows = [
            {
                "job_id": job_id,
                "position": index,
                "name": ref.name,
                "kind": ref.kind.value,
                "reference": ref.reference,
                "size_bytes": ref.size_bytes,
                "sha256": ref.sha256,
            }
            for index, ref in enumerate(artifacts)
        ]
        with self._engine.begin() as conn:
            conn.execute(sa.delete(job_artifacts).where(job_artifacts.c.job_id == job_id))
            if rows:
                conn.execute(sa.insert(job_artifacts), rows)

    def list_artifacts(self, job_id: JobId) -> list[JobArtifactRef]:
        t = job_artifacts.c
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(t.name, t.kind, t.reference, t.size_bytes, t.sha256)
                .where(t.job_id == job_id)
                .order_by(t.position)
            ).all()
        return [JobArtifactRef(r.name, ArtifactKind(r.kind), r.reference, int(r.size_bytes), r.sha256) for r in rows]
