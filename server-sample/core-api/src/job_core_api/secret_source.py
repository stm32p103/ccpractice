"""秘密情報の取得のポート(contracts/ports.md「SecretSource」)。

秘密の値を、設定ファイルの平文ではなく、実行環境の保管機能から取得する。値は、ログ・例外・応答に出さない。
実装は composition root(core-server)が選ぶ。環境変数の実装は開発・試験専用。
"""

from __future__ import annotations

from typing import Protocol


class SecretNotFound(Exception):
    """名前に対応する秘密がない。値・探した場所の詳細を含めない。"""


class SecretSource(Protocol):
    def get(self, name: str) -> str: ...
