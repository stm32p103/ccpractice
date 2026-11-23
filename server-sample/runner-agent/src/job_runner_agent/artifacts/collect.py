"""成果物の収集(research.md R11。FR-018)。

作業フォルダ内の、パターンに一致する通常のファイルだけを対象にする。リパースポイント(シンボリックリンク・ジャンクション)
は辿らず、収集もしない。件数・1 ファイルの大きさ・合計の上限を超えたら ArtifactLimitExceeded。
パターンは、パスの検査と同じ規則(`..`、絶対、ドライブ、UNC、デバイス、代替ストリーム など)を通す。`*`・`?`・`**`
を使える。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..guard.fs_win import is_reparse_point
from ..guard.workpath import PathRejected, WorkFolder, check_relative


class ArtifactLimitExceeded(Exception):
    """件数・大きさ・合計の上限を超えた。"""


@dataclass(frozen=True)
class CollectedFile:
    path: Path
    name: str
    size: int


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """作業フォルダ直下からの相対パターンを検査して、正規表現にする。違反は PathRejected。"""
    placeholder = pattern.replace("**", "x").replace("*", "x").replace("?", "x")
    check_relative(placeholder)
    parts = []
    for piece in pattern.replace("/", "\\").split("\\"):
        if piece in ("", "."):
            continue
        if piece == "**":
            parts.append(r"(?:[^\\]+\\)*")
            continue
        regex = "".join(".*" if c == "*" else "[^\\\\]" if c == "?" else re.escape(c) for c in piece.replace("**", "*"))
        parts.append(regex + r"\\")
    body = "".join(parts)
    body = body[:-2] if body.endswith(r"\\") else body
    return re.compile("^" + body + "$", re.IGNORECASE)


def collect(
    folder: WorkFolder, patterns: list[str], *, max_files: int, max_file_bytes: int, max_total_bytes: int
) -> list[CollectedFile]:
    compiled = [compile_pattern(p) for p in patterns]  # PathRejected はそのまま送出
    found: list[CollectedFile] = []
    total = 0
    used_names: set[str] = set()
    for directory, subdirs, files in os.walk(folder.root, followlinks=False):
        current = Path(directory)
        subdirs[:] = sorted(d for d in subdirs if not is_reparse_point(current / d))
        for file_name in sorted(files):
            path = current / file_name
            if is_reparse_point(path) or not path.is_file():
                continue
            relative = str(path.relative_to(folder.root))
            if not any(c.match(relative) for c in compiled):
                continue
            if not folder.verify_existing(path):
                continue
            size = path.stat().st_size
            if size > max_file_bytes:
                raise ArtifactLimitExceeded
            total += size
            if total > max_total_bytes or len(found) + 1 > max_files:
                raise ArtifactLimitExceeded
            name, counter = file_name, 1
            while name.lower() in used_names:
                counter += 1
                name = f"{path.stem}-{counter}{path.suffix}"
            used_names.add(name.lower())
            found.append(CollectedFile(path, name, size))
    return found


__all__ = ["ArtifactLimitExceeded", "CollectedFile", "PathRejected", "collect", "compile_pattern"]
