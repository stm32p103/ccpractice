"""形式B: Doxygen の行末コメント + キー: 値 の並び"""
from __future__ import annotations

import re

from ..base import KeyValue, RegexCommentParser, Sample


class KeyValueCommentParser[T](RegexCommentParser[T, KeyValue]):
    """`///< unit: 単位, lsb: 式, ofs: 式, desc: 説明`。キーは小文字に正規化する。

    判定の特徴: `///<` で始まり, `キー: 値` を 1 つ以上含む。
    parsed のキー: unit, lsb, ofs, desc (書かれているものだけ)
    """

    pattern = re.compile(r"///<\s*(?P<body>\w+\s*:.*)", re.S)

    samples = (
        Sample("///< unit: mV, lsb: 5, ofs: -2560, desc: 電圧",
               {"unit": "mV", "lsb": "5", "ofs": "-2560", "desc": "電圧"}, "sample.c"),
        Sample("///< unit: -, lsb: 1, ofs: 0, desc: 2次元テーブル",
               {"unit": "-", "lsb": "1", "ofs": "0", "desc": "2次元テーブル"}, "sample.c"),
    )

    @classmethod
    def to_parsed(cls, m: re.Match[str]) -> KeyValue | None:
        kv = {}
        for part in m.group("body").split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                kv[k.strip().lower()] = v.strip()
        return kv or None
