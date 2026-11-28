"""ソースからコメントを取り出す (宣言行の周りのコメント候補の抽出)"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class _Comment:
    start: int      # 開始行 (1 始まり)
    end: int        # 終了行
    text: str       # コメント記号を含む生テキスト
    leading: bool   # 行頭からコメントが始まっている (前にコードがない)


def scan_comments(source: str) -> list[_Comment]:
    """ソース全体からコメントを列挙する (文字列・文字リテラル内は無視)"""
    out, i, line, n = [], 0, 1, len(source)
    line_has_code = False
    while i < n:
        c = source[i]
        if c == "\n":
            line += 1
            line_has_code = False
            i += 1
        elif source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j < 0 else j
            out.append(_Comment(line, line, source[i:j].rstrip(), not line_has_code))
            i = j
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            text = source[i:j]
            out.append(_Comment(line, line + text.count("\n"), text, not line_has_code))
            line += text.count("\n")
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and source[j] != c and source[j] != "\n":
                j += 2 if source[j] == "\\" else 1
            i = j + 1
            line_has_code = True
        else:
            if not c.isspace():
                line_has_code = True
            i += 1
    return out


def extract_comments(comments: Sequence[_Comment], decl_line: int) -> list[str]:
    """宣言行 decl_line に対応するコメント候補を, 近い順に返す。

    1. 宣言行で始まるコメント (行末コメント: `int x; /* ... */`)
    2. 宣言の直前の行で終わる, 行頭から始まるコメントのまとまり (連続する // 行は 1 件に連結)
    """
    trailing = [c.text for c in comments if c.start == decl_line and not c.leading]
    above = []
    expect_end = decl_line - 1
    for c in sorted((c for c in comments if c.leading and c.end < decl_line), key=lambda c: -c.end):
        if c.end != expect_end:
            break
        above.insert(0, c)
        expect_end = c.start - 1
    leading = []
    for c in above:  # 連続した // 行は 1 件にまとめ, /* */ はそれぞれ 1 件
        if leading and c.text.startswith("//") and leading[-1].startswith("//"):
            leading[-1] += "\n" + c.text
        else:
            leading.append(c.text)
    return trailing + leading[::-1]
