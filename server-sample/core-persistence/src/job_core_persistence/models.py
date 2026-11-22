"""表の定義(SQLAlchemy Core。data-model.md §5)。

集約は JSONB の文書(`doc`)として保存し、検索・一意性・順序づけに要る項目だけを列に出す。
楽観的排他の `version` は列で持つ。
一意性(削除されていないランナーの名前、ジョブ・ランナーごとの ACTIVE なリース、ランナーごとの有効なトークン、
認証情報の名前・ハッシュ、セッションのハッシュ)は、(部分)一意の索引で DB が保証する。
トークンの値・パスワード・認証基盤の生の応答は、どの表にも保存しない(ハッシュだけ)。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()
TS = DateTime(timezone=True)

jobs = Table(
    "jobs",
    metadata,
    Column("job_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("state", String, nullable=False),
    Column("owner", String, nullable=False),
    Column("submitted_at", TS, nullable=False),
    Column("finished_at", TS),
    Column("assigned_runner_id", String),
    Column("retry_of", String),
    Column("duplicate_key", Text),
    Column("doc", JSONB, nullable=False),
    Index("ix_jobs_submitted", text("submitted_at DESC"), text("job_id DESC")),
    Index("ix_jobs_owner", "owner"),
    Index("ix_jobs_state", "state"),
    Index("ix_jobs_runner", "assigned_runner_id"),
    Index("ix_jobs_retry_of", "retry_of"),
    Index("ix_jobs_duplicate", "duplicate_key", postgresql_where=text("state = 'queued'")),
)

queue = Table(
    "queue",
    metadata,
    Column("queue_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("doc", JSONB, nullable=False),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("seq", BigInteger, Identity(), primary_key=True),
    Column("record_id", String, nullable=False, unique=True),
    Column("occurred_at", TS, nullable=False),
    Column("job_id", String),
    Column("actor", String, nullable=False),
    Column("operation", String, nullable=False),
    Column("outcome", String, nullable=False),
    Column("runner_id", String),
    Column("doc", JSONB, nullable=False),
    Index("ix_audit_order", "occurred_at", "record_id"),
    Index("ix_audit_job", "job_id"),
)

outbox = Table(
    "outbox",
    metadata,
    Column("seq", BigInteger, Identity(), primary_key=True),
    Column("event_id", String, nullable=False, unique=True),
    Column("status", String, nullable=False),
    Column("recorded_at", TS, nullable=False),
    Column("dispatched_at", TS),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("doc", JSONB, nullable=False),
    Index("ix_outbox_pending", "seq", postgresql_where=text("status = 'pending'")),
)

runners = Table(
    "runners",
    metadata,
    Column("runner_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("name", String, nullable=False),
    Column("deleted", Boolean, nullable=False),
    Column("doc", JSONB, nullable=False),
    Index("ux_runners_name_active", "name", unique=True, postgresql_where=text("NOT deleted")),
)

leases = Table(
    "leases",
    metadata,
    Column("lease_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("job_id", String, nullable=False),
    Column("runner_id", String, nullable=False),
    Column("status", String, nullable=False),
    Column("expires_at", TS, nullable=False),
    Column("doc", JSONB, nullable=False),
    Index("ux_leases_job_active", "job_id", unique=True, postgresql_where=text("status = 'active'")),
    Index("ux_leases_runner_active", "runner_id", unique=True, postgresql_where=text("status = 'active'")),
)

runner_tokens = Table(
    "runner_tokens",
    metadata,
    Column("token_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("runner_id", String, nullable=False),
    Column("token_hash", String, nullable=False),
    Column("revoked", Boolean, nullable=False),
    Column("doc", JSONB, nullable=False),
    Index("ix_runner_tokens_hash", "token_hash"),
    Index("ux_runner_tokens_valid", "runner_id", unique=True, postgresql_where=text("NOT revoked")),
)

capability_allowlist = Table(
    "capability_allowlist",
    metadata,
    Column("id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("doc", JSONB, nullable=False),
)

service_credentials = Table(
    "service_credentials",
    metadata,
    Column("credential_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("permissions", ARRAY(String), nullable=False),
    Column("subject_id", String, nullable=False),
    Column("token_hash", String, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("created_by", String, nullable=False),
    Column("revoked_at", TS),
    Column("last_used_at", TS),
    Column("version", Integer, nullable=False),
    Index("ux_service_credentials_hash", "token_hash", unique=True),
    Index("ux_service_credentials_name_active", "name", unique=True, postgresql_where=text("revoked_at IS NULL")),
)

sessions = Table(
    "sessions",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("token_hash", String, nullable=False),
    Column("subject_id", String, nullable=False),
    Column("display_name", String),
    Column("groups", ARRAY(String), nullable=False),
    Column("created_at", TS, nullable=False),
    Column("last_used_at", TS, nullable=False),
    Column("expires_at", TS, nullable=False),
    Column("revoked_at", TS),
    Index("ux_sessions_hash", "token_hash", unique=True),
    Index("ix_sessions_subject", "subject_id"),
    Index("ix_sessions_expires", "expires_at"),
    Index("ix_sessions_revoked", "revoked_at"),
)
