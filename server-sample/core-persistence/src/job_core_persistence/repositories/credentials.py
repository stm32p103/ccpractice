"""サービス用の認証情報とセッションのリポジトリ(003 contracts/ports.md)。

各呼び出しが独立した短いトランザクション。値(トークン)は保存せず、SHA-256 のハッシュだけを保存する。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from job_core.access.permission import Permission
from job_core.job.domain.errors import ConcurrencyConflict
from job_core.shared.ids import SubjectId
from job_core_api.access.models import ServiceCredential, Session
from job_core_api.access.ports import DuplicateCredentialName
from job_core_api.access.secrets import TokenHash

from ..models import service_credentials, sessions


def _credential(row: Any) -> ServiceCredential:
    return ServiceCredential(
        credential_id=row.credential_id,
        name=row.name,
        subject_id=SubjectId(row.subject_id),
        permissions=frozenset(Permission(p) for p in row.permissions),
        token_hash=TokenHash(row.token_hash),
        created_at=row.created_at,
        created_by=SubjectId(row.created_by),
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        version=row.version,
    )


class SqlServiceCredentialRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, credential: ServiceCredential) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    sa.insert(service_credentials).values(
                        credential_id=credential.credential_id,
                        name=credential.name,
                        permissions=sorted(p.value for p in credential.permissions),
                        subject_id=credential.subject_id,
                        token_hash=credential.token_hash,
                        created_at=credential.created_at,
                        created_by=credential.created_by,
                        revoked_at=credential.revoked_at,
                        last_used_at=credential.last_used_at,
                        version=credential.version,
                    )
                )
        except IntegrityError:
            raise DuplicateCredentialName() from None

    def get(self, credential_id: str) -> ServiceCredential | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(service_credentials).where(service_credentials.c.credential_id == credential_id)
            ).first()
        return None if row is None else _credential(row)

    def find_by_hash(self, token_hash: TokenHash) -> ServiceCredential | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(service_credentials).where(service_credentials.c.token_hash == token_hash)
            ).first()
        return None if row is None else _credential(row)

    def save(self, credential: ServiceCredential) -> None:
        """version は、保存済みの version + 1 でなければ衝突。失効を有効に戻す保存は拒否する(失効は一方向)。"""
        t = service_credentials
        with self._engine.begin() as conn:
            result = conn.execute(
                sa.update(t)
                .where(
                    t.c.credential_id == credential.credential_id,
                    t.c.version == credential.version - 1,
                    sa.or_(t.c.revoked_at.is_(None), sa.literal(credential.revoked_at is not None)),
                )
                .values(
                    revoked_at=credential.revoked_at, last_used_at=credential.last_used_at, version=credential.version
                )
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict("認証情報が同時に更新された、または失効を取り消せない")

    def list(self) -> list[ServiceCredential]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(service_credentials).order_by(
                    service_credentials.c.created_at, service_credentials.c.credential_id
                )
            ).all()
        return [_credential(r) for r in rows]


def _session(row: Any) -> Session:
    return Session(
        session_id=row.session_id,
        token_hash=TokenHash(row.token_hash),
        subject_id=SubjectId(row.subject_id),
        groups=frozenset(row.groups),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        display_name=row.display_name,
        revoked_at=row.revoked_at,
    )


class SqlSessionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, session: Session) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.insert(sessions).values(
                    session_id=session.session_id,
                    token_hash=session.token_hash,
                    subject_id=session.subject_id,
                    display_name=session.display_name,
                    groups=sorted(session.groups),
                    created_at=session.created_at,
                    last_used_at=session.last_used_at,
                    expires_at=session.expires_at,
                    revoked_at=session.revoked_at,
                )
            )

    def find_by_hash(self, token_hash: TokenHash) -> Session | None:
        with self._engine.connect() as conn:
            row = conn.execute(sa.select(sessions).where(sessions.c.token_hash == token_hash)).first()
        return None if row is None else _session(row)

    def touch(self, session_id: str, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.update(sessions)
                .where(sessions.c.session_id == session_id, sessions.c.last_used_at < at)
                .values(last_used_at=at)
            )

    def revoke(self, session_id: str, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.update(sessions)
                .where(sessions.c.session_id == session_id, sessions.c.revoked_at.is_(None))
                .values(revoked_at=at)
            )

    def revoke_all_of(self, subject_id: SubjectId, at: datetime) -> int:
        with self._engine.begin() as conn:
            result = conn.execute(
                sa.update(sessions)
                .where(sessions.c.subject_id == subject_id, sessions.c.revoked_at.is_(None), sessions.c.expires_at > at)
                .values(revoked_at=at)
            )
        return int(result.rowcount)

    def delete_inactive_before(self, cutoff: datetime) -> int:
        with self._engine.begin() as conn:
            result = conn.execute(
                sa.delete(sessions).where(
                    sa.or_(
                        sessions.c.revoked_at < cutoff,
                        sa.and_(sessions.c.revoked_at.is_(None), sessions.c.expires_at < cutoff),
                    )
                )
            )
        return int(result.rowcount)
