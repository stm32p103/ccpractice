"""arm-none-eabi-gcc 向けの DWARF 解析。

検証: arm-none-eabi-gcc 15.3.1, -mcpu=cortex-m4 -O0 -g3, -gdwarf-2/3/4/5
     (verification/sample.c + verification/lvalues.txt,
     結果は verification/results/arm_gcc/v2〜v5/result.md)

観察された特徴 (いずれも標準 DWARF の範囲で, DwarfSource のままで正しく読める):
- 変数のアドレスは DW_OP_addr (v5 でも DW_OP_addrx は使われない)
- ビットフィールド: v2〜v4 は DW_AT_bit_offset (MSB 基準), v5 は DW_AT_data_bit_offset
- v2 は DW_AT_data_member_location がブロック形式 (DW_OP_plus_uconst)
- 関数内 static は関数の DIE の子に DW_OP_addr 付きで出る。シンボル名は "name.N"
  (ElfSymtabSource の既定の local_static_pattern と一致)
- static 変数のシンボルは STT_NOTYPE (ElfSymtabSource で対応済み)
"""
from __future__ import annotations

from .common import DwarfSource


class ArmGccDwarfSource(DwarfSource):
    """arm-none-eabi-gcc の DWARF。標準どおりなのでフックの上書きはない"""

    toolchain = "arm-none-eabi-gcc"
