"""コメント形式の集約と検査 (カタログ生成・衝突確認・自己テスト)。

devtools/comment_catalog.py (集約) と devtools/comment_check.py (新しい形式の候補の確認) から使う。
衝突 = ある形式の pattern が, ほかの形式のサンプルに合致すること。誤作動防止のため許容しない。
"""
from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
import re
from dataclasses import dataclass, field

from .base import RegexCommentParser, Sample

FORMATS_PKG = __package__ + ".formats"
FORMATS_DIR = os.path.join(os.path.dirname(__file__), "formats")


@dataclass
class FormatInfo:
    cls: type[RegexCommentParser]
    module: str
    parsed_type: str
    doc: str
    problems: list[str] = field(default_factory=list)

    @property
    def name(self):
        return self.cls.__name__


def _parsed_type(cls) -> str:
    """RegexCommentParser[T, P] の P の表記"""
    for base in getattr(cls, "__orig_bases__", ()):
        args = getattr(base, "__args__", ())
        if len(args) == 2:
            p = args[1]
            return getattr(p, "__name__", None) or str(p)
    return "?"


def discover() -> list[FormatInfo]:
    """formats/ 以下の各モジュールから, そのモジュールで定義された RegexCommentParser のサブクラスを集める"""
    out = []
    for mi in sorted(pkgutil.iter_modules([FORMATS_DIR]), key=lambda m: m.name):
        if mi.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{FORMATS_PKG}.{mi.name}")
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if issubclass(cls, RegexCommentParser) and cls.__module__ == mod.__name__:
                out.append(FormatInfo(cls, mi.name, _parsed_type(cls), inspect.cleandoc(cls.__doc__ or "")))
    return out


def self_test(fi: FormatInfo) -> list[str]:
    """形式自身のサンプルに合致し, 期待どおりの parsed になるか"""
    probs = []
    if not getattr(fi.cls, "pattern", None):
        return ["pattern がない"]
    if not fi.cls.samples:
        probs.append("samples がない (衝突確認ができない)")
    for s in fi.cls.samples:
        got = fi.cls.extract_parsed(s.comment)
        if got is None:
            probs.append(f"自分のサンプルに合致しない: {s.comment!r}")
        elif s.expected is not None and got != s.expected:
            probs.append(f"抽出結果が期待と違う: {s.comment!r} → {got!r} (期待 {s.expected!r})")
    return probs


@dataclass
class Collision:
    pattern_owner: str
    """合致してしまった pattern の持ち主 (形式名, または "候補")"""
    sample_owner: str
    """合致されたサンプルの持ち主"""
    comment: str


def collisions(formats: list[FormatInfo]) -> list[Collision]:
    """登録済みの形式どうしの衝突"""
    out = []
    for a in formats:
        for b in formats:
            if a is b:
                continue
            for s in b.cls.samples:
                if a.cls.match(s.comment):
                    out.append(Collision(a.name, b.name, s.comment))
    return out


def check_candidate(pattern: re.Pattern[str], comments: list[Sample], formats: list[FormatInfo],
                    exclude: tuple[str, ...] = ()) -> dict:
    """新しい形式の候補 (pattern と, 利用者の抜粋から取り出したコメント) を確認する。

    exclude : 置き換え対象の既存形式 (既存形式の pattern を更新する場合に, 自分自身を除く)
    戻り値:
      matches   : 候補の pattern が各コメントに合致したか, と名前付きグループの値
      taken     : 既存形式が抜粋のコメントに合致した (= 衝突)
      intrudes  : 候補の pattern が既存形式のサンプルに合致した (= 衝突)
    """
    fs = [f for f in formats if f.name not in exclude]
    matches, taken, intrudes = [], [], []
    for c in comments:
        m = pattern.fullmatch(c.comment.strip())
        matches.append((c, m.groupdict() if m else None))
        for f in fs:
            if f.cls.match(c.comment):
                taken.append(Collision(f.name, "候補", c.comment))
    for f in fs:
        for s in f.cls.samples:
            if pattern.fullmatch(s.comment.strip()):
                intrudes.append(Collision("候補", f.name, s.comment))
    return {"matches": matches, "taken": taken, "intrudes": intrudes}


# ---------------------------------------------------------------- 生成

INIT_HEADER = '''"""コメント形式の一覧。

dsr-comment-catalog --write (devtools/comment_catalog.py) で自動生成する。手で編集しない。
形式を追加するときは, このディレクトリにモジュールを置いてから再生成する。
"""
'''


def write_init(formats: list[FormatInfo]):
    lines = [INIT_HEADER]
    for f in formats:
        lines.append(f"from .{f.module} import {f.name}")
    lines.append("")
    lines.append("ALL_FORMATS = [" + ", ".join(f.name for f in formats) + "]")
    lines.append('"""登録済みの形式 (モジュール名順。優先度ではない。優先度は SymbolResolver に渡す順で決める)"""')
    lines.append("")
    lines.append("__all__ = [" + ", ".join(repr(n) for n in ["ALL_FORMATS"] + [f.name for f in formats]) + "]")
    with open(os.path.join(FORMATS_DIR, "__init__.py"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


def catalog_markdown(formats: list[FormatInfo], cols: list[Collision]) -> str:
    L = ["# コメント形式カタログ", "",
         "`dsr-comment-catalog --write` (devtools/comment_catalog.py) で自動生成。手で編集しない。", "",
         "| 形式 (クラス) | モジュール | parsed | サンプル数 | 状態 |", "|---|---|---|---|---|"]
    for f in formats:
        st = "OK" if not f.problems else "要確認: " + "; ".join(f.problems).replace("|", "\\|")
        L.append(f"| `{f.name}` | `formats/{f.module}.py` | `{f.parsed_type}` | {len(f.cls.samples)} | {st} |")
    L += ["", "## 衝突", ""]
    L += [f"- `{c.pattern_owner}` の pattern が `{c.sample_owner}` のサンプル `{c.comment}` に合致" for c in cols] \
        or ["- なし"]
    for f in formats:
        L += ["", f"## {f.name}", "", f.doc, "", f"- モジュール: `formats/{f.module}.py`",
              f"- parsed: `{f.parsed_type}`", "", "判定・抽出の正規表現 (fullmatch, 前後の空白は除去):", "",
              "```regex", f.cls.pattern.pattern, "```", "", "| サンプル | 期待する parsed | 出典 |", "|---|---|---|"]
        for s in f.cls.samples:
            L.append(f"| `{s.comment}` | `{s.expected!r}` | {s.source or '-'} |".replace("\n", "⏎"))
    return "\n".join(L) + "\n"
