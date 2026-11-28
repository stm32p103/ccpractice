"""処理系ごとに差し替える情報源 (デバッグ情報, アドレス)"""
from .base import DebugInfoSource, SymbolAddressSource
from .dwarf import ArmGccDwarfSource, DwarfSource
from .elf_symtab import ElfSymtabSource

__all__ = ["DebugInfoSource", "SymbolAddressSource", "DwarfSource", "ArmGccDwarfSource",
           "ElfSymtabSource"]
