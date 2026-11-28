"""DWARF (v2〜v5) を pyelftools で読み, model に変換する DebugInfoSource の共通実装。

標準の DWARF の意味どおりに解釈する。処理系ごとの癖は, このクラスを継承して
「フック」(下の ---- フック ---- 節のメソッド) を上書きして吸収する。
例: arm_gcc.py の ArmGccDwarfSource。新しい処理系は同じディレクトリに追加する。
"""
from __future__ import annotations

import os

from elftools.elf.elffile import ELFFile

from ...errors import ResolveError
from ...model import (ArrayType, BaseType, CType, Encoding, EnumType, Linkage, Member, PointerType,
                      SourceLoc, StructType, Variable)

_CV = ("DW_TAG_typedef", "DW_TAG_volatile_type", "DW_TAG_const_type", "DW_TAG_restrict_type",
       "DW_TAG_atomic_type")

DW_ATE = {0x02: Encoding.BOOL, 0x04: Encoding.FLOAT, 0x05: Encoding.SIGNED, 0x06: Encoding.SIGNED,
          0x07: Encoding.UNSIGNED, 0x08: Encoding.UNSIGNED}
"""DW_AT_encoding の値 → Encoding (DW_ATE_boolean, float, signed, signed_char, unsigned, unsigned_char)"""

DW_OP_ADDR = 0x03
DW_OP_ADDRX = 0xA1
DW_OP_PLUS_UCONST = 0x23


# ---------------------------------------------------------------- DIE ヘルパ

def attr(die, name, default=None):
    """属性の値 (なければ default)"""
    a = die.attributes.get(name)
    return a.value if a is not None else default


def die_name(die) -> str | None:
    """DW_AT_name (なければ DW_AT_specification / DW_AT_abstract_origin 先の名前)"""
    n = attr(die, "DW_AT_name")
    if n is None:
        for ref in ("DW_AT_specification", "DW_AT_abstract_origin"):
            if ref in die.attributes:
                return die_name(die.get_DIE_from_attribute(ref))
    return n.decode() if isinstance(n, bytes) else n


def type_of(die):
    """DW_AT_type が指す DIE (なければ None = void)"""
    return die.get_DIE_from_attribute("DW_AT_type") if "DW_AT_type" in die.attributes else None


def strip_cv(die):
    """typedef / const / volatile などを剥がした実体の型"""
    while die is not None and die.tag in _CV:
        die = type_of(die)
    return die


def has_volatile(die) -> bool:
    while die is not None and die.tag in _CV:
        if die.tag == "DW_TAG_volatile_type":
            return True
        die = type_of(die)
    return False


def uleb128(data, i):
    v = shift = 0
    while True:
        b = data[i]
        i += 1
        v |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return v, i


# ---------------------------------------------------------------- 本体

class DwarfSource:
    """標準 DWARF の DebugInfoSource。

    elf_path : DWARF 付きの ELF。リンク済みの実行ファイルを想定 (再配置は適用しない)
    """

    toolchain = "generic"
    """対応する処理系の名前 (describe() に使う)"""

    def __init__(self, elf_path: str):
        self.elf_path = elf_path
        self._f = open(elf_path, "rb")
        self.elf = ELFFile(self._f)
        if not self.elf.has_dwarf_info():
            self._f.close()
            raise ResolveError(f"DWARF がない: {elf_path}")
        self.dwarf = self.elf.get_dwarf_info()
        self.little_endian = self.elf.little_endian
        self.cu_versions: list[tuple[str, int]] = []
        self._var_dies: dict[str, list[tuple[object, str, str | None]]] = {}
        self._vars: dict[int, Variable] = {}
        self._enums: dict[str, int] = {}
        self._types: dict[int, CType] = {}
        self._index()

    # ---- DebugInfoSource
    def find_variables(self, name: str) -> list[Variable]:
        out = []
        for die, unit, func in self._var_dies.get(name, []):
            if die.offset not in self._vars:
                self._vars[die.offset] = self._convert_variable(die, unit, func)
            out.append(self._vars[die.offset])
        return out

    def enum_value(self, name: str) -> int | None:
        return self._enums.get(name)

    def describe(self) -> str:
        vs = sorted({v for _, v in self.cu_versions})
        return f"DWARF v{'/'.join(map(str, vs))} ({self.toolchain})"

    def close(self):
        self._f.close()

    # ---- 索引
    def _index(self):
        for cu in self.dwarf.iter_CUs():
            top = cu.get_top_DIE()
            unit = os.path.basename(die_name(top) or "")
            self.cu_versions.append((unit, cu["version"]))
            self._walk(top, unit, None)

    def _walk(self, die, unit, func):
        for c in die.iter_children():
            if c.tag == "DW_TAG_variable":
                if attr(c, "DW_AT_declaration"):
                    continue  # extern 宣言 (定義は別の DIE)
                if func is not None and not self.is_static_storage(c):
                    continue  # 自動変数
                n = die_name(c)
                if n:
                    self._var_dies.setdefault(n, []).append((c, unit, func))
            elif c.tag == "DW_TAG_subprogram":
                self._walk(c, unit, die_name(c))
            elif c.tag == "DW_TAG_lexical_block":
                self._walk(c, unit, func)
            elif c.tag == "DW_TAG_enumeration_type":
                for e in c.iter_children():
                    if e.tag == "DW_TAG_enumerator":
                        self._enums[die_name(e)] = attr(e, "DW_AT_const_value")

    # ---- フック (処理系ごとの癖はここを上書きする) ----------------------------

    def variable_address(self, die) -> int | None:
        """変数のアドレス。DW_AT_location が DW_OP_addr 1 命令の場合のみ対応"""
        loc = attr(die, "DW_AT_location")
        if isinstance(loc, list) and loc and loc[0] == DW_OP_ADDR:
            n = die.cu["address_size"]
            return int.from_bytes(bytes(loc[1:1 + n]), "little" if self.little_endian else "big")
        return None  # DW_OP_addrx やロケーションリストは未対応 → SymbolAddressSource で補う

    def is_static_storage(self, die) -> bool:
        """関数内の変数が static (固定アドレス) か"""
        loc = attr(die, "DW_AT_location")
        return isinstance(loc, list) and bool(loc) and loc[0] in (DW_OP_ADDR, DW_OP_ADDRX)

    def linkage_of(self, die, func: str | None) -> Linkage:
        if func is not None:
            return Linkage.LOCAL_STATIC
        return Linkage.EXTERNAL if attr(die, "DW_AT_external") else Linkage.INTERNAL

    def member_offset(self, die) -> int:
        """DW_AT_data_member_location (定数, または DWARF2 のブロック DW_OP_plus_uconst)"""
        v = attr(die, "DW_AT_data_member_location", 0)
        if isinstance(v, list):
            if v and v[0] == DW_OP_PLUS_UCONST:
                return uleb128(v, 1)[0]
            raise ResolveError(f"未対応の data_member_location: {v}")
        return v

    def bitfield_pos(self, die, unit_size: int) -> int:
        """ビットフィールドの構造体先頭からのビット位置 (model の定義に正規化)。

        DWARF4+ : DW_AT_data_bit_offset (構造体先頭から, 下位ビット側から数える)
        DWARF2/3: DW_AT_bit_offset (格納単位 = DW_AT_byte_size の MSB から数える) と
                  DW_AT_data_member_location (格納単位の位置)
        """
        bs = attr(die, "DW_AT_bit_size")
        if "DW_AT_data_bit_offset" in die.attributes:
            if not self.little_endian:
                raise ResolveError("ビッグエンディアンのビットフィールドは未対応 (サブクラスで対応)")
            return attr(die, "DW_AT_data_bit_offset")
        bo = attr(die, "DW_AT_bit_offset")
        if bo is None:
            raise ResolveError(f"ビットフィールドの位置属性がない: {die_name(die)}")
        if not self.little_endian:
            raise ResolveError("ビッグエンディアンのビットフィールドは未対応 (サブクラスで対応)")
        return self.member_offset(die) * 8 + unit_size * 8 - bo - bs

    def base_encoding(self, die) -> Encoding | None:
        return DW_ATE.get(attr(die, "DW_AT_encoding"))

    def enum_encoding(self, die) -> Encoding | None:
        """元の整数型 (DWARF3+ の DW_AT_type) があればその符号, なければ列挙子の値の範囲で決める"""
        under = strip_cv(type_of(die))
        if under is not None and under.tag == "DW_TAG_base_type":
            return self.base_encoding(under)
        vals = [attr(e, "DW_AT_const_value", 0) for e in die.iter_children() if e.tag == "DW_TAG_enumerator"]
        return Encoding.SIGNED if any(v < 0 for v in vals) else Encoding.UNSIGNED

    def decl(self, die) -> SourceLoc | None:
        """DW_AT_decl_file / DW_AT_decl_line → SourceLoc。ファイル番号は v5 で 0 始まり, v4 以前は 1 始まり"""
        line, fidx = attr(die, "DW_AT_decl_line"), attr(die, "DW_AT_decl_file")
        if line is None or fidx is None:
            return None
        lp = self.dwarf.line_program_for_CU(die.cu)
        if lp is None:
            return None
        entries = lp["file_entry"]
        idx = fidx if lp.header["version"] >= 5 else fidx - 1
        if not 0 <= idx < len(entries):
            return None
        return SourceLoc(entries[idx].name.decode(), line)

    def type_display_name(self, die) -> str:
        """表示用の型名。typedef があれば typedef 名 (前に付いた修飾子を含む)"""
        parts = []
        while die is not None and die.tag in _CV:
            if die.tag == "DW_TAG_typedef":
                return " ".join(parts + [die_name(die)])
            parts.append(die.tag[7:-5])  # volatile / const ...
            die = type_of(die)
        if die is None:
            return " ".join(parts + ["void"])
        n = die_name(die) or {"DW_TAG_structure_type": "struct", "DW_TAG_union_type": "union",
                              "DW_TAG_array_type": "array", "DW_TAG_enumeration_type": "enum",
                              "DW_TAG_pointer_type": "pointer"}.get(die.tag, die.tag)
        return " ".join(parts + [n])

    # ---- 変換 ----------------------------------------------------------------

    def _convert_variable(self, die, unit, func) -> Variable:
        return Variable(name=die_name(die), linkage=self.linkage_of(die, func), unit=unit, func=func,
                        type=self.convert_type(type_of(die)), address=self.variable_address(die),
                        decl=self.decl(die))

    def convert_type(self, die) -> CType:
        key = die.offset if die is not None else -1
        if key in self._types:
            return self._types[key]
        name = self.type_display_name(die)
        vol = has_volatile(die)
        base = strip_cv(die)
        if base is None:
            t = BaseType(name, vol, 0, None)
        elif base.tag == "DW_TAG_base_type":
            t = BaseType(name, vol, attr(base, "DW_AT_byte_size"), self.base_encoding(base))
        elif base.tag == "DW_TAG_enumeration_type":
            t = EnumType(name, vol, attr(base, "DW_AT_byte_size"), self.enum_encoding(base),
                         {die_name(e): attr(e, "DW_AT_const_value") for e in base.iter_children()
                          if e.tag == "DW_TAG_enumerator"})
        elif base.tag == "DW_TAG_pointer_type":
            t = PointerType(name, vol, attr(base, "DW_AT_byte_size") or base.cu["address_size"])
        elif base.tag in ("DW_TAG_structure_type", "DW_TAG_union_type"):
            t = StructType(name, vol, attr(base, "DW_AT_byte_size", 0), base.tag == "DW_TAG_union_type")
            self._types[key] = t  # 先に登録 (自己参照対策)
            for m in base.iter_children():
                if m.tag == "DW_TAG_member" and die_name(m):
                    t.members[die_name(m)] = self._convert_member(m)
        elif base.tag == "DW_TAG_array_type":
            dims = [self._count(sr) for sr in base.iter_children() if sr.tag == "DW_TAG_subrange_type"]
            t = ArrayType(name, vol, self.convert_type(type_of(base)), dims)
        else:
            t = BaseType(name, vol, attr(base, "DW_AT_byte_size", 0), None)
        self._types[key] = t
        return t

    def _convert_member(self, m) -> Member:
        mt = self.convert_type(type_of(m))
        bs = attr(m, "DW_AT_bit_size")
        if bs is None:
            return Member(die_name(m), mt, self.member_offset(m), decl=self.decl(m))
        unit_size = attr(m, "DW_AT_byte_size") or mt.size
        pos = self.bitfield_pos(m, unit_size)
        return Member(die_name(m), mt, pos // 8, pos, bs, self.decl(m))

    @staticmethod
    def _count(sr) -> int | None:
        if "DW_AT_count" in sr.attributes:
            return attr(sr, "DW_AT_count")
        ub = attr(sr, "DW_AT_upper_bound")
        if ub is None or not isinstance(ub, int):
            return None
        return ub - attr(sr, "DW_AT_lower_bound", 0) + 1
