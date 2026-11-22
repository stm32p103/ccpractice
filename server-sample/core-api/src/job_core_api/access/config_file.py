"""TOML の AccessConfigSource(research.md R6)。呼び出しごとにファイルを読み直す(キャッシュしない)。

ファイルの欠落・構文の誤りは AccessConfigInvalid(違反の場所と理由だけ。内容の抜粋を含めない)にする。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .config import AccessConfig, AccessConfigInvalid, Violation


class TomlAccessConfigSource:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> AccessConfig:
        try:
            with self._path.open("rb") as stream:
                data = tomllib.load(stream)
        except FileNotFoundError:
            raise AccessConfigInvalid([Violation("file", "設定ファイルがない")]) from None
        except OSError:
            raise AccessConfigInvalid([Violation("file", "設定ファイルを読めない")]) from None
        except tomllib.TOMLDecodeError:
            raise AccessConfigInvalid([Violation("file", "TOML として解釈できない")]) from None
        return AccessConfig.from_mapping(data)
