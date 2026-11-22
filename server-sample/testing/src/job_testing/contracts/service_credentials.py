"""サービス用の認証情報とセッションのポートの契約テスト(contracts/ports.md)。

使い方: テストのクラスで継承し、`credentials`(ServiceCredentialRepository)・`sessions`(SessionRepository)
フィクスチャを定義する。永続化は空の状態から始めること。core-persistence(実アダプタ)も同じクラスを継承する。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from job_core.access.permission import Permission
from job_core.job.domain.errors import ConcurrencyConflict
from job_core.shared.ids import SubjectId
from job_core_api.access.models import ServiceCredential, Session
from job_core_api.access.ports import DuplicateCredentialName, ServiceCredentialRepository, SessionRepository
from job_core_api.access.secrets import TokenHash, hash_token

T0 = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)


def make_credential(
    credential_id: str = "c1", name: str = "svc-a", secret: str | None = None, **overrides: object
) -> ServiceCredential:
    values: dict[str, object] = {
        "credential_id": credential_id,
        "name": name,
        "subject_id": SubjectId(f"svc:{credential_id}"),
        "permissions": frozenset({Permission.JOB_SUBMIT, Permission.GENERAL}),
        "token_hash": hash_token(secret or f"st_secret-{credential_id}"),
        "created_at": T0,
        "created_by": SubjectId("admin"),
    }
    values.update(overrides)
    return ServiceCredential(**values)  # type: ignore[arg-type]


def make_session(
    session_id: str = "s1", subject: str = "u1", secret: str | None = None, **overrides: object
) -> Session:
    values: dict[str, object] = {
        "session_id": session_id,
        "token_hash": hash_token(secret or f"ss_secret-{session_id}"),
        "subject_id": SubjectId(subject),
        "groups": frozenset({"g1"}),
        "created_at": T0,
        "last_used_at": T0,
        "expires_at": T0 + timedelta(hours=12),
    }
    values.update(overrides)
    return Session(**values)  # type: ignore[arg-type]


class ServiceCredentialContract:
    def test_add_and_get(self, credentials: ServiceCredentialRepository) -> None:
        credential = make_credential()
        credentials.add(credential)
        assert credentials.get("c1") == credential
        assert credentials.get("unknown") is None
        assert [c.credential_id for c in credentials.list()] == ["c1"]

    def test_find_by_hash_includes_revoked_and_unknown_is_none(self, credentials: ServiceCredentialRepository) -> None:
        credential = make_credential()
        credentials.add(credential)
        found = credentials.find_by_hash(credential.token_hash)
        assert found is not None and found.credential_id == "c1"
        revoked = credential.revoke(T0 + timedelta(minutes=1))
        credentials.save(revoked)
        found = credentials.find_by_hash(credential.token_hash)
        assert found is not None and found.revoked_at is not None
        assert credentials.find_by_hash(TokenHash("0" * 64)) is None

    def test_duplicate_active_name_is_rejected_but_allowed_after_revoke(
        self, credentials: ServiceCredentialRepository
    ) -> None:
        credentials.add(make_credential("c1", "svc-a"))
        with pytest.raises(DuplicateCredentialName):
            credentials.add(make_credential("c2", "svc-a"))
        credentials.save(credentials.get("c1").revoke(T0))  # type: ignore[union-attr]
        credentials.add(make_credential("c2", "svc-a"))
        assert {c.credential_id for c in credentials.list()} == {"c1", "c2"}

    def test_duplicate_hash_is_rejected(self, credentials: ServiceCredentialRepository) -> None:
        credentials.add(make_credential("c1", "svc-a", secret="st_same"))
        with pytest.raises(DuplicateCredentialName):
            credentials.add(make_credential("c2", "svc-b", secret="st_same"))

    def test_revoke_is_one_way(self, credentials: ServiceCredentialRepository) -> None:
        credential = make_credential()
        credentials.add(credential)
        revoked = credential.revoke(T0 + timedelta(minutes=1))
        credentials.save(revoked)
        reactivated = ServiceCredential(
            credential_id=revoked.credential_id,
            name=revoked.name,
            subject_id=revoked.subject_id,
            permissions=revoked.permissions,
            token_hash=revoked.token_hash,
            created_at=revoked.created_at,
            created_by=revoked.created_by,
            revoked_at=None,
            version=revoked.version + 1,
        )
        with pytest.raises(ConcurrencyConflict):
            credentials.save(reactivated)
        stored = credentials.get("c1")
        assert stored is not None and stored.revoked_at == T0 + timedelta(minutes=1)

    def test_save_with_stale_version_conflicts(self, credentials: ServiceCredentialRepository) -> None:
        credential = make_credential()
        credentials.add(credential)
        credentials.save(credential.used(T0 + timedelta(minutes=1)))
        with pytest.raises(ConcurrencyConflict):
            credentials.save(credential.revoke(T0 + timedelta(minutes=2)))

    def test_repr_does_not_contain_the_hash(self) -> None:
        credential = make_credential()
        assert credential.token_hash not in repr(credential)


class SessionContract:
    def test_add_and_find(self, sessions: SessionRepository) -> None:
        session = make_session()
        sessions.add(session)
        assert sessions.find_by_hash(session.token_hash) == session
        assert sessions.find_by_hash(TokenHash("0" * 64)) is None

    def test_revoke_is_idempotent_and_found_afterwards(self, sessions: SessionRepository) -> None:
        session = make_session()
        sessions.add(session)
        sessions.revoke("s1", T0 + timedelta(minutes=1))
        sessions.revoke("s1", T0 + timedelta(minutes=5))
        found = sessions.find_by_hash(session.token_hash)
        assert found is not None and found.revoked_at == T0 + timedelta(minutes=1)
        sessions.revoke("unknown", T0)

    def test_revoke_all_of_counts_only_active_sessions_of_the_subject(self, sessions: SessionRepository) -> None:
        sessions.add(make_session("s1", "u1"))
        sessions.add(make_session("s2", "u1"))
        sessions.add(make_session("s3", "u2"))
        sessions.revoke("s2", T0)
        assert sessions.revoke_all_of(SubjectId("u1"), T0 + timedelta(minutes=1)) == 1
        assert sessions.revoke_all_of(SubjectId("u1"), T0 + timedelta(minutes=2)) == 0
        other = sessions.find_by_hash(make_session("s3", "u2").token_hash)
        assert other is not None and other.revoked_at is None

    def test_touch_never_moves_backwards(self, sessions: SessionRepository) -> None:
        session = make_session()
        sessions.add(session)
        sessions.touch("s1", T0 + timedelta(minutes=10))
        sessions.touch("s1", T0 + timedelta(minutes=5))
        found = sessions.find_by_hash(session.token_hash)
        assert found is not None and found.last_used_at == T0 + timedelta(minutes=10)

    def test_delete_inactive_before_keeps_active_sessions(self, sessions: SessionRepository) -> None:
        sessions.add(make_session("active", "u1", expires_at=T0 + timedelta(days=30)))
        sessions.add(make_session("expired", "u2", expires_at=T0 + timedelta(hours=1)))
        sessions.add(make_session("revoked", "u3"))
        sessions.revoke("revoked", T0 + timedelta(hours=1))
        sessions.add(make_session("recent_revoked", "u4"))
        sessions.revoke("recent_revoked", T0 + timedelta(days=9))
        deleted = sessions.delete_inactive_before(T0 + timedelta(days=8))
        assert deleted == 2
        assert sessions.find_by_hash(make_session("active").token_hash) is not None
        assert sessions.find_by_hash(make_session("recent_revoked").token_hash) is not None
        assert sessions.find_by_hash(make_session("expired").token_hash) is None
        assert sessions.find_by_hash(make_session("revoked").token_hash) is None
