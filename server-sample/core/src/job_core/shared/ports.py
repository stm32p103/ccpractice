"""時刻と識別子の発行のポート(contracts/ports.md「Clock / IdGenerator」)。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """現在時刻を返す。タイムゾーン付きの UTC を返すこと。"""

    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    """一意な識別子(空でない文字列)を発行する。"""

    def new_id(self) -> str: ...


class SecretGenerator(Protocol):
    """ランナーのトークンを作る(contracts/ports.md「SecretGenerator」)。"""

    def new_token(self) -> str:
        """`rt_` + 32 バイトの乱数の URL 安全な文字列を返す。"""
        ...
