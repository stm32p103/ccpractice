"""トークンの補助(research.md R4)。

値は 32 バイトの乱数に種類の接頭辞を付けたもの。保存するのは SHA-256 のハッシュだけで、比較は定数時間で行う。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from enum import StrEnum
from typing import NewType

TokenHash = NewType("TokenHash", str)

SESSION_PREFIX = "ss_"
SERVICE_PREFIX = "st_"
RUNNER_PREFIX = "rt_"


class TokenKind(StrEnum):
    SESSION = "session"
    SERVICE = "service"
    RUNNER = "runner"


def new_token(kind: TokenKind) -> str:
    """`ss_`・`st_` の値を発行する。ランナーのトークンは job_core が発行する(002)。"""
    if kind is TokenKind.SESSION:
        prefix = SESSION_PREFIX
    elif kind is TokenKind.SERVICE:
        prefix = SERVICE_PREFIX
    else:
        raise ValueError("ランナーのトークンは job_core が発行する")
    return prefix + secrets.token_urlsafe(32)


def token_kind_of(value: str) -> TokenKind | None:
    """値の先頭から種類を判別する。どれにも当たらなければ None。"""
    if value.startswith(SESSION_PREFIX):
        return TokenKind.SESSION
    if value.startswith(SERVICE_PREFIX):
        return TokenKind.SERVICE
    if value.startswith(RUNNER_PREFIX):
        return TokenKind.RUNNER
    return None


def hash_token(value: str) -> TokenHash:
    return TokenHash(hashlib.sha256(value.encode("utf-8")).hexdigest())


def hashes_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
