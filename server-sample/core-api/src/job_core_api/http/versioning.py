"""版の扱い(research.md R3。FR-019)。

URL に版を含める(`/v1`)。互換を保つ変更(項目・エンドポイントの追加)は同じ版で行い、破壊的変更は新しい版で提供する。
旧版を残す互換期間(3 か月以上)は、旧版の応答に `Deprecation` と `Sunset` を付けて知らせる(設定で有効にする)。
"""

from __future__ import annotations

from ..settings import ApiSettings

API_VERSION = "1.0.0"
API_PREFIX = "/v1"
MAJOR_VERSION = 1


def version_headers(settings: ApiSettings, path: str) -> list[tuple[bytes, bytes]]:
    """旧版であることを示す応答ヘッダ(`Sunset` の日付が設定されたときだけ)。"""
    if settings.deprecation_sunset is None or not path.startswith(API_PREFIX + "/"):
        return []
    return [
        (b"deprecation", b"true"),
        (b"sunset", settings.deprecation_sunset.encode("ascii")),
    ]
