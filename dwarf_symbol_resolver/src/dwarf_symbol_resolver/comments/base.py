"""コメントパーサの基底クラス。

コメントパーサは 2 段階で処理する。

    parse(comment: str) -> T | None
        1. extract(comment) -> P | None   … 形式の判定と項目の抽出 (形式ごとに実装。ライブラリ側)
        2. build(parsed: P) -> T          … 抽出結果 (parsed) から T を作る (利用者が自ツールで実装)

P (parsed) は Key-Value 形式 (KeyValue = dict[str, str]) か dataclass (fields.py)。
T はパッケージの利用者が自ツールの開発時に決める。

形式 (formats/ 以下) は RegexCommentParser を継承し, 判定・抽出の正規表現 (pattern) と
その形式のサンプル (samples) を持つ。build は抽象のまま残し, 利用者がサブクラスで実装する。

    class MyBracket(BracketCommentParser[MyInfo]):
        def build(self, parsed: MonitorFields) -> MyInfo: ...

同じ parsed 型を返す形式が複数あれば, build だけを書いた mixin を先頭に置いて共有できる:

    class MonitorBuild:
        def build(self, parsed: MonitorFields) -> MyInfo: ...
    class MyBracket(MonitorBuild, BracketCommentParser[MyInfo]): pass
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

type KeyValue = dict[str, str]
"""Key-Value 形式の parsed (キーは形式ごとに正規化した名前)"""


@dataclass(frozen=True)
class Sample:
    """形式のサンプル (カタログ・衝突確認・自己テストに使う)"""

    comment: str
    """コメント記号を含むコメント文字列 (例 "/* [rpm] LSB=1/128 */")"""
    expected: Any = None
    """このコメントから抽出されるべき parsed。None なら「合致すること」だけを確認する"""
    source: str = ""
    """出典 (利用者が示した抜粋のファイル名・行など)"""


class CommentParser[T, P](ABC):
    """コメント 1 件を解析して T を返す。

    parse() に渡す文字列はコメント記号を含むソース上の生のテキスト
    (例: "/* [rpm] LSB=1/128 */", "///< unit: mV, lsb: 5")。
    """

    def parse(self, comment: str) -> T | None:
        """自分の形式なら T を, そうでなければ None を返す"""
        parsed = self.extract(comment)
        return None if parsed is None else self.build(parsed)

    @abstractmethod
    def extract(self, comment: str) -> P | None:
        """形式に合致すれば抽出結果 (parsed) を, 合致しなければ None を返す"""

    @abstractmethod
    def build(self, parsed: P) -> T:
        """抽出結果から T を作る (パッケージの利用者が実装する)"""


class RegexCommentParser[T, P](CommentParser[T, P]):
    """正規表現で判定・抽出する形式の基底。

    pattern : コメント全体 (前後の空白を除く) に fullmatch させる正規表現。
              合致すれば「この形式」と判定し, 名前付きグループから parsed を作る
    samples : この形式のサンプル。ほかの形式の pattern がこれに合致してはならない (衝突)
    """

    pattern: ClassVar[re.Pattern[str]]
    samples: ClassVar[tuple[Sample, ...]] = ()

    @classmethod
    def match(cls, comment: str) -> re.Match[str] | None:
        return cls.pattern.fullmatch(comment.strip())

    @classmethod
    def extract_parsed(cls, comment: str) -> Any:
        """extract() のクラスメソッド版 (build を実装していなくても使える。カタログ・検査用)"""
        m = cls.match(comment)
        return None if m is None else cls.to_parsed(m)

    def extract(self, comment: str) -> P | None:
        return self.extract_parsed(comment)

    @classmethod
    @abstractmethod
    def to_parsed(cls, m: re.Match[str]) -> P | None:
        """正規表現の合致結果から parsed を作る。項目が足りないなどで形式外とみなすなら None"""


def parse_first[T](parsers: Sequence[CommentParser[T, Any]], comments: Sequence[str]) -> T | None:
    """パーサの優先度 (インデックスの若い順) を外側, コメント候補を内側にして試し, 最初の結果を返す。

    つまり優先度の高いパーサが合致するコメントがあれば, それより前の候補に
    優先度の低いパーサが合致するコメントがあっても, 優先度の高い方を採用する。
    """
    for p in parsers:
        for c in comments:
            r = p.parse(c)
            if r is not None:
                return r
    return None
