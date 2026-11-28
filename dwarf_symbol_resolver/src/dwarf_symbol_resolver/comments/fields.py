"""dataclass 形式の parsed (抽出結果)。複数の形式で共有できる。

値は加工しない文字列のまま持つ (数値化などは利用者の build で行う。numbers.eval_fraction が使える)。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonitorFields:
    """RAM モニタ向けの項目"""

    unit: str | None = None
    """単位 (例 "rpm")"""
    lsb: str | None = None
    """LSB (重み) の表記 (例 "1/(128*1000)")"""
    offset: str | None = None
    """オフセットの表記 (例 "-40")"""
    description: str | None = None
    """説明"""
