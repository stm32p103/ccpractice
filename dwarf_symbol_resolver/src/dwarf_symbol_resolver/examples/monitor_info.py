"""dwarf_symbol_resolver の利用例: RAM モニタツール側で T (MonitorInfo) を決め, 各形式の build を実装する。

T はパッケージの利用者 (このファイル = ツール開発者) が決める。ライブラリ側の形式
(BracketCommentParser など) は extract までを担当し, build はここで実装する。
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from dwarf_symbol_resolver import BracketCommentParser, KeyValue, KeyValueCommentParser, MonitorFields, try_fraction


@dataclass(frozen=True)
class MonitorInfo:
    """RAM モニタツールに設定する情報 (この例での T)"""

    unit: str | None = None
    lsb: Fraction | None = None
    """1 カウントあたりの物理量 (評価できなければ None)"""
    offset: Fraction | None = None
    """物理値 = 生値 * lsb + offset"""
    description: str | None = None
    lsb_expr: str | None = None
    offset_expr: str | None = None
    style: str | None = None
    """どの形式で書かれていたか"""


class BracketMonitorParser(BracketCommentParser[MonitorInfo]):
    def build(self, parsed: MonitorFields) -> MonitorInfo:
        return MonitorInfo(parsed.unit, try_fraction(parsed.lsb), try_fraction(parsed.offset),
                           parsed.description, parsed.lsb, parsed.offset, "A")


class KeyValueMonitorParser(KeyValueCommentParser[MonitorInfo]):
    def build(self, parsed: KeyValue) -> MonitorInfo:
        return MonitorInfo(parsed.get("unit"), try_fraction(parsed.get("lsb")), try_fraction(parsed.get("ofs")),
                           parsed.get("desc"), parsed.get("lsb"), parsed.get("ofs"), "B")


MONITOR_PARSERS = [BracketMonitorParser(), KeyValueMonitorParser()]
"""先頭ほど優先"""
