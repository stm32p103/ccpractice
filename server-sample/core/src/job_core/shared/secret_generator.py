"""SecretGenerator の既定の実装(標準ライブラリの secrets を使う。research.md R9)。"""

from __future__ import annotations

import secrets

TOKEN_PREFIX = "rt_"


class SystemSecretGenerator:
    """暗号論的な乱数(32 バイト = 256 ビット)からトークンを作る。"""

    def new_token(self) -> str:
        return TOKEN_PREFIX + secrets.token_urlsafe(32)
