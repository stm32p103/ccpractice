"""認証・アクセスのポート(contracts/ports.md)。

実装は Fake(job_testing.api_fakes)、実アダプタ(job_core_persistence、005 の認証アダプタ)。
値(トークン)そのものは、ポートに渡らない。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from job_core.shared.ids import SubjectId

from .config import AccessConfig, AccessConfigInvalid, Violation
from .models import ServiceCredential, Session, VerifiedIdentity
from .secrets import TokenHash

__all__ = [
    "AccessConfigInvalid",
    "AccessConfigSource",
    "DuplicateCredentialName",
    "IdentityProvider",
    "IdentityProviderUnavailable",
    "IdentityRejected",
    "LoginRedirect",
    "ServiceCredentialRepository",
    "SessionRepository",
    "Violation",
]


class IdentityRejected(Exception):
    """証明を確認できなかった。メッセージに証明の値・認証基盤の生の応答を含めない。"""


class IdentityProviderUnavailable(Exception):
    """認証基盤が使えない(API は 503 identity_provider_unavailable)。"""


class DuplicateCredentialName(Exception):
    """有効な認証情報に同名がある、またはハッシュが重複した。"""


@dataclass(frozen=True)
class LoginRedirect:
    """利用者を認証基盤へ送る遷移先。"""

    url: str


class IdentityProvider(Protocol):
    def begin_login(self, return_to: str) -> LoginRedirect | None:
        """遷移の要らない方式(直接の証明だけ)は None。return_to は不透明な値として保持する。"""
        ...

    def complete_login(self, params: Mapping[str, str]) -> VerifiedIdentity:
        """確認できなければ IdentityRejected、認証基盤が使えなければ IdentityProviderUnavailable。"""
        ...


class ServiceCredentialRepository(Protocol):
    def add(self, credential: ServiceCredential) -> None: ...
    def get(self, credential_id: str) -> ServiceCredential | None: ...
    def find_by_hash(self, token_hash: TokenHash) -> ServiceCredential | None:
        """失効済みも返す(呼び出し側が revoked_at を見る)。未知は None。"""
        ...

    def save(self, credential: ServiceCredential) -> None:
        """version が一致しなければ ConcurrencyConflict。失効を有効に戻す保存は拒否する。"""
        ...

    def list(self) -> list[ServiceCredential]: ...


class SessionRepository(Protocol):
    def add(self, session: Session) -> None: ...
    def find_by_hash(self, token_hash: TokenHash) -> Session | None:
        """失効・期限切れも返す(判定は呼び出し側。Session.is_active)。"""
        ...

    def touch(self, session_id: str, at: datetime) -> None:
        """last_used_at を at に更新する(巻き戻さない)。"""
        ...

    def revoke(self, session_id: str, at: datetime) -> None:
        """冪等(失効済みなら何もしない)。"""
        ...

    def revoke_all_of(self, subject_id: SubjectId, at: datetime) -> int:
        """有効なセッションを失効させ、その件数を返す。"""
        ...

    def delete_inactive_before(self, cutoff: datetime) -> int:
        """失効または期限切れから cutoff より前の記録を削除する。有効なセッションは削除しない。"""
        ...


class AccessConfigSource(Protocol):
    def load(self) -> AccessConfig:
        """検証済みの設定を返す。不正なら AccessConfigInvalid。呼び出しごとに読み直す。"""
        ...
