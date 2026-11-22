"""認証・セッションのモデル(data-model.md §1)。

repr にハッシュ・値を含めない(T-A1)。権限はセッションに保存せず、呼び出しごとに導く(R5)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from job_core.access.permission import Permission
from job_core.shared.ids import SubjectId

from .secrets import TokenHash

MAX_GROUPS = 128
MAX_GROUP_LENGTH = 256
MAX_SUBJECT_LENGTH = 256
MAX_DISPLAY_NAME_LENGTH = 128
MAX_CREDENTIAL_NAME_LENGTH = 128
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class InvalidModel(ValueError):
    """モデルの項目が data-model.md の制約を満たさない。"""


def _check_text(name: str, value: str, max_length: int) -> None:
    if not value or not value.strip():
        raise InvalidModel(f"{name} は空でない文字列でなければならない")
    if len(value) > max_length:
        raise InvalidModel(f"{name} は {max_length} 文字以内でなければならない")
    if _CONTROL.search(value):
        raise InvalidModel(f"{name} に制御文字は使えない")


@dataclass(frozen=True)
class VerifiedIdentity:
    """認証基盤が確認した本人性と所属グループ(VerifiedIdentity.subject_id、.display_name、.groups)。"""

    subject_id: SubjectId
    groups: frozenset[str] = frozenset()
    display_name: str | None = None

    def __post_init__(self) -> None:
        _check_text("subject_id", self.subject_id, MAX_SUBJECT_LENGTH)
        groups = frozenset(self.groups)
        if len(groups) > MAX_GROUPS:
            raise InvalidModel(f"groups は {MAX_GROUPS} 個以内でなければならない")
        for group in groups:
            _check_text("groups の要素", group, MAX_GROUP_LENGTH)
        object.__setattr__(self, "groups", groups)
        if self.display_name is not None:
            _check_text("display_name", self.display_name, MAX_DISPLAY_NAME_LENGTH)


@dataclass(frozen=True)
class ServiceCredential:
    credential_id: str
    name: str
    subject_id: SubjectId
    permissions: frozenset[Permission]
    token_hash: TokenHash = field(repr=False)
    created_at: datetime
    created_by: SubjectId
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _check_text("name", self.name, MAX_CREDENTIAL_NAME_LENGTH)
        object.__setattr__(self, "permissions", frozenset(Permission(p) for p in self.permissions))

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def revoke(self, at: datetime) -> ServiceCredential:
        """失効は一方向。失効済みを再度失効させても失効日時は変えない。"""
        if self.revoked_at is not None:
            return self
        return replace(self, revoked_at=at, version=self.version + 1)

    def used(self, at: datetime) -> ServiceCredential:
        """最後に認証に成功した日時を進める(巻き戻さない)。"""
        if self.last_used_at is not None and at <= self.last_used_at:
            return self
        return replace(self, last_used_at=at, version=self.version + 1)


@dataclass(frozen=True)
class Session:
    session_id: str
    token_hash: TokenHash = field(repr=False)
    subject_id: SubjectId
    groups: frozenset[str]
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    display_name: str | None = None
    revoked_at: datetime | None = None

    def is_active(self, now: datetime, idle_timeout: timedelta) -> bool:
        """有効の判定: 失効しておらず、絶対期限と無操作の期限の内(Session.expires_at、.last_used_at、.revoked_at)。"""
        if self.revoked_at is not None:
            return False
        if now >= self.expires_at:
            return False
        return now - self.last_used_at < idle_timeout

    def idle_expires_at(self, idle_timeout: timedelta) -> datetime:
        """次の操作がなければ失効する日時(絶対期限を超えない)。"""
        return min(self.last_used_at + idle_timeout, self.expires_at)
