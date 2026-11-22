"""偽の認証基盤と、認証・セッション・アクセス設定のメモリ上の実装(contracts/ports.md)。通信しない。"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime

from job_core.job.domain.errors import ConcurrencyConflict
from job_core.shared.ids import SubjectId
from job_core_api.access.config import AccessConfig
from job_core_api.access.models import ServiceCredential, Session, VerifiedIdentity
from job_core_api.access.ports import (
    AccessConfigSource,
    DuplicateCredentialName,
    IdentityProviderUnavailable,
    IdentityRejected,
    LoginRedirect,
)
from job_core_api.access.secrets import TokenHash


class FakeIdentityProvider:
    """試験が与える対応表から本人性を返す偽の認証基盤。

    直接の証明(`proof`)は `{"subject": ..., "groups": "g1,g2", "display_name": ...}`。
    事前に register した利用者は `{"subject": ...}` だけで確認できる。遷移は使わない(begin_login は None)。
    """

    def __init__(self, *, redirect_url: str | None = None) -> None:
        self._known: dict[str, VerifiedIdentity] = {}
        self._redirect_url = redirect_url
        self.available = True
        self.accept_unregistered = True
        self.begun: list[str] = []

    def register(
        self, subject: str, groups: frozenset[str] | set[str] = frozenset(), display_name: str | None = None
    ) -> None:
        self._known[subject] = VerifiedIdentity(SubjectId(subject), frozenset(groups), display_name)

    def begin_login(self, return_to: str) -> LoginRedirect | None:
        if not self.available:
            raise IdentityProviderUnavailable()
        if self._redirect_url is None:
            return None
        self.begun.append(return_to)
        return LoginRedirect(self._redirect_url)

    def complete_login(self, params: Mapping[str, str]) -> VerifiedIdentity:
        if not self.available:
            raise IdentityProviderUnavailable()
        subject = params.get("subject")
        if not subject:
            raise IdentityRejected()
        known = self._known.get(subject)
        if known is not None and "groups" not in params:
            return known
        if not self.accept_unregistered and known is None:
            raise IdentityRejected()
        groups = frozenset(g for g in params.get("groups", "").split(",") if g)
        try:
            return VerifiedIdentity(SubjectId(subject), groups, params.get("display_name"))
        except ValueError as exc:
            raise IdentityRejected() from exc


class InMemoryServiceCredentialRepository:
    def __init__(self) -> None:
        self._items: dict[str, ServiceCredential] = {}
        self._lock = threading.RLock()

    def add(self, credential: ServiceCredential) -> None:
        with self._lock:
            if credential.credential_id in self._items:
                raise DuplicateCredentialName()
            for existing in self._items.values():
                if existing.token_hash == credential.token_hash:
                    raise DuplicateCredentialName()
                if existing.revoked_at is None and credential.revoked_at is None and existing.name == credential.name:
                    raise DuplicateCredentialName()
            self._items[credential.credential_id] = credential

    def get(self, credential_id: str) -> ServiceCredential | None:
        with self._lock:
            return self._items.get(credential_id)

    def find_by_hash(self, token_hash: TokenHash) -> ServiceCredential | None:
        with self._lock:
            for item in self._items.values():
                if item.token_hash == token_hash:
                    return item
            return None

    def save(self, credential: ServiceCredential) -> None:
        """version は呼び出し側が +1 した値を渡す(保存済みの version + 1 でなければ衝突)。"""
        with self._lock:
            current = self._items.get(credential.credential_id)
            if current is None:
                raise ConcurrencyConflict("認証情報が存在しない")
            if credential.version != current.version + 1:
                raise ConcurrencyConflict("version が一致しない")
            if current.revoked_at is not None and credential.revoked_at is None:
                raise ConcurrencyConflict("失効した認証情報を有効に戻せない")
            self._items[credential.credential_id] = credential

    def list(self) -> list[ServiceCredential]:
        with self._lock:
            return sorted(self._items.values(), key=lambda c: (c.created_at, c.credential_id))


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._items: dict[str, Session] = {}
        self._lock = threading.RLock()

    def add(self, session: Session) -> None:
        with self._lock:
            duplicate_hash = any(s.token_hash == session.token_hash for s in self._items.values())
            if session.session_id in self._items or duplicate_hash:
                raise ValueError("セッションが重複している")
            self._items[session.session_id] = session

    def find_by_hash(self, token_hash: TokenHash) -> Session | None:
        with self._lock:
            for item in self._items.values():
                if item.token_hash == token_hash:
                    return item
            return None

    def touch(self, session_id: str, at: datetime) -> None:
        with self._lock:
            current = self._items.get(session_id)
            if current is not None and at > current.last_used_at:
                self._items[session_id] = replace(current, last_used_at=at)

    def revoke(self, session_id: str, at: datetime) -> None:
        with self._lock:
            current = self._items.get(session_id)
            if current is not None and current.revoked_at is None:
                self._items[session_id] = replace(current, revoked_at=at)

    def revoke_all_of(self, subject_id: SubjectId, at: datetime) -> int:
        with self._lock:
            count = 0
            for session_id, item in list(self._items.items()):
                if item.subject_id == subject_id and item.revoked_at is None and at < item.expires_at:
                    self._items[session_id] = replace(item, revoked_at=at)
                    count += 1
            return count

    def delete_inactive_before(self, cutoff: datetime) -> int:
        with self._lock:
            doomed = [
                session_id
                for session_id, item in self._items.items()
                if (item.revoked_at is not None and item.revoked_at < cutoff)
                or (item.revoked_at is None and item.expires_at < cutoff)
            ]
            for session_id in doomed:
                del self._items[session_id]
            return len(doomed)

    def all(self) -> list[Session]:
        with self._lock:
            return list(self._items.values())


class InMemoryAccessConfigSource(AccessConfigSource):
    """設定の値を差し替えられる AccessConfigSource。load のたびに supplier を呼ぶ。"""

    def __init__(self, supplier: Callable[[], AccessConfig] | AccessConfig) -> None:
        self._supplier = supplier

    def replace(self, supplier: Callable[[], AccessConfig] | AccessConfig) -> None:
        self._supplier = supplier

    def load(self) -> AccessConfig:
        supplier = self._supplier
        return supplier() if callable(supplier) else supplier
