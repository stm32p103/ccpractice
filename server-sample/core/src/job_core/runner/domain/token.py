"""RunnerToken 集約とハッシュ(data-model.md §5。research.md R9)。

トークンの値は保存せず、SHA-256 の 16 進文字列だけを保存する。乱数が 256 ビットあるため、
遅い鍵導出関数は要らない。照合は hmac.compare_digest で行う。
repr・例外のメッセージにハッシュ・値を出さない(SC-008)。
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime

from job_core.shared.ids import RunnerId

from .values import TokenHash


def hash_token(token: str) -> TokenHash:
    """トークンの値から、保存用のハッシュを作る。"""
    return TokenHash(hashlib.sha256(token.encode("utf-8")).hexdigest())


@dataclass(frozen=True)
class IssuedToken:
    """発行の結果。value は発行のユースケースの戻り値にだけ現れる。repr に値を出さない。"""

    token_id: str
    value: str = field(repr=False)

    def __repr__(self) -> str:
        return f"IssuedToken(token_id={self.token_id!r}, value=***)"

    def __str__(self) -> str:
        return repr(self)


@dataclass(eq=False)
class RunnerToken:
    token_id: str
    runner_id: RunnerId
    token_hash: TokenHash
    issued_at: datetime
    revoked_at: datetime | None = None
    version: int = 0

    def __repr__(self) -> str:
        return f"RunnerToken(token_id={self.token_id!r}, runner_id={self.runner_id!r}, revoked={self.is_revoked})"

    @classmethod
    def issue(cls, *, token_id: str, runner_id: RunnerId, token_hash: TokenHash, at: datetime) -> RunnerToken:
        if not token_id:
            raise ValueError("token_id は空でない文字列でなければならない")
        return cls(token_id=token_id, runner_id=runner_id, token_hash=token_hash, issued_at=at)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def matches(self, candidate: TokenHash) -> bool:
        """定数時間の比較。失効済みでも真偽は返す(失効の判定は is_revoked で行う)。"""
        return hmac.compare_digest(self.token_hash.value.encode("ascii"), candidate.value.encode("ascii"))

    def revoke(self, at: datetime) -> bool:
        """失効させる。既に失効していれば何もしない。変化したかを返す。"""
        if self.revoked_at is not None:
            return False
        self.revoked_at = at
        return True
