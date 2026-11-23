"""パスの検査と作業フォルダ(research.md R5・R7。data-model.md §4 の不変条件 1)。

`WorkPath` は検査済みの値で、`WorkFolder.resolve()` だけが作る。ツールの引数・作業ディレクトリ・成果物のパターンは
すべてここを通す。拒否は文字列の検査と実ファイルの検査(リパースポイント)の両方で行う。
PathRejected のメッセージは拒否の種類だけを持つ(入力の文字列を含めない。監査には detail を別に渡す)。
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .fs_win import is_reparse_point

_DRIVE = re.compile(r"^[A-Za-z]:")
_FORBIDDEN_CHARS = set('<>"|?*')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}
SUBFOLDERS = ("work", "src", "tmp", "signal")


class PathRejected(ValueError):
    """作業フォルダ外を指す、または検査に通らないパス。kind は固定の語彙。"""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(kind)
        self.kind = kind
        self.detail = detail[:200]


def check_relative(rel: str) -> tuple[str, ...]:
    """文字列だけの検査。通れば、正規化した要素の列を返す(`.` と空の要素は除く)。"""
    if not isinstance(rel, str) or not rel.strip():
        raise PathRejected("empty", str(rel))
    if any(ord(c) < 32 for c in rel):
        raise PathRejected("invalid_char", rel)
    text = rel.replace("/", "\\")
    if text.startswith("\\\\?\\") or text.startswith("\\\\.\\"):
        raise PathRejected("device", rel)
    if text.startswith("\\\\"):
        raise PathRejected("unc", rel)
    if _DRIVE.match(text):
        raise PathRejected("drive", rel)
    if text.startswith("\\"):
        raise PathRejected("absolute", rel)
    parts: list[str] = []
    for part in text.split("\\"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PathRejected("parent", rel)
        if ":" in part:
            raise PathRejected("stream", rel)
        if part != part.rstrip(" .") or part != part.lstrip():
            raise PathRejected("trailing", rel)
        if _FORBIDDEN_CHARS & set(part):
            raise PathRejected("invalid_char", rel)
        if part.split(".")[0].upper() in _RESERVED:
            raise PathRejected("reserved", rel)
        parts.append(part)
    if not parts:
        raise PathRejected("empty", rel)
    return tuple(parts)


_TOKEN = object()


@dataclass(frozen=True)
class WorkPath:
    """作業フォルダ内の検査済みの絶対パス。WorkFolder.resolve() 以外では作れない。"""

    path: Path
    rel: str
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _TOKEN:
            raise TypeError("WorkPath は WorkFolder.resolve() で作る")

    def __str__(self) -> str:
        return str(self.path)


class WorkFolder:
    """ジョブごとに新規に作る作業フォルダ。ツールの作業ディレクトリは work\\ 。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._resolved_root = root.resolve()

    @classmethod
    def create(cls, base: Path, job_id: str) -> WorkFolder:
        """`<base>\\<job_id>-<乱数>` を新規に作る(既存なら失敗)。job_id は検査して使う。"""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", job_id)[:64] or "job"
        root = base / f"{safe}-{secrets.token_hex(6)}"
        base.mkdir(parents=True, exist_ok=True)
        root.mkdir(exist_ok=False)
        for name in SUBFOLDERS:
            (root / name).mkdir()
        return cls(root)

    def path_of(self, name: str) -> WorkPath:
        """固定のサブフォルダ(work、src、tmp、signal)。"""
        if name not in SUBFOLDERS:
            raise PathRejected("not_a_subfolder", name)
        return WorkPath(self.root / name, name, _TOKEN)

    def resolve(self, rel: str) -> WorkPath:
        """作業フォルダの直下からの相対パスを検査して、WorkPath にする。"""
        parts = check_relative(rel)
        current = self.root
        for part in parts:
            current = current / part
            if is_reparse_point(current):
                raise PathRejected("reparse_point", rel)
        resolved = current.resolve()
        if not resolved.is_relative_to(self._resolved_root):
            raise PathRejected("escape", rel)
        return WorkPath(current, "\\".join(parts), _TOKEN)

    def resolve_under(self, base: str, rel: str) -> WorkPath:
        """base(work、src など)の直下からの相対パス rel を検査する。rel 自体を先に検査する(base の付与で、
        UNC・ドライブなどの形が隠れないようにする)。"""
        check_relative(rel)
        return self.resolve(base + "\\" + rel)

    def verify_existing(self, path: Path) -> bool:
        """既存のパスが、リパースポイントを経由せず作業フォルダ内にあるか(成果物の収集時の再検査)。"""
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return False
        current = self.root
        for part in relative.parts:
            current = current / part
            if is_reparse_point(current):
                return False
        return path.resolve().is_relative_to(self._resolved_root)

    def delete(self, attempts: int = 3) -> bool:
        """作業フォルダを削除する(リンク先を辿らない)。成功すれば真。"""
        for attempt in range(attempts):
            try:
                shutil.rmtree(self.root, onexc=_make_writable)
            except FileNotFoundError:
                return True
            except OSError:
                time.sleep(0.05 * (attempt + 1))
                continue
            if not self.root.exists():
                return True
        return not self.root.exists()


def _make_writable(function: object, path: str, _exc: BaseException) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.remove(path)
    except OSError:
        pass
