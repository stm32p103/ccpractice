"""DWARF の DebugInfoSource 実装。処理系ごとに 1 ファイル (common.DwarfSource を継承) を置く。"""
from .arm_gcc import ArmGccDwarfSource
from .common import DwarfSource

__all__ = ["DwarfSource", "ArmGccDwarfSource"]
