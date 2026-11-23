"""ファイルシステムの判定(リパースポイント。research.md R7)。標準ライブラリだけで判定する。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_point(path: Path) -> bool:
    """シンボリックリンク・ジャンクションなど、リパースポイントであれば真(存在しなければ偽)。リンクを辿らない。"""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    return bool(hasattr(os.path, "isjunction") and os.path.isjunction(path))
