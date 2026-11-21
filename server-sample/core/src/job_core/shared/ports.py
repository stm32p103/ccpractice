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
