"""ELF のシンボル表からアドレスを得る SymbolAddressSource"""
from __future__ import annotations

import re

from elftools.elf.elffile import ELFFile

from ..model import Linkage, Variable


class ElfSymtabSource:
    """ELF の .symtab から変数のアドレスを引く。

    local_static_pattern : 関数内 static のシンボル名の正規表現 ({name} が変数名に置き換わる)。
                           GCC は "call_cnt.0" のように番号を付ける。
    ファイル内 static はシンボル表の STT_FILE (直前のファイル名シンボル) で翻訳単位を区別する。
    """

    name = "ELF シンボル表"

    def __init__(self, elf_path: str, local_static_pattern: str = r"{name}\.\d+"):
        self.local_static_pattern = local_static_pattern
        self.symbols = self._load(elf_path)

    @staticmethod
    def _load(elf_path):
        out = []
        with open(elf_path, "rb") as f:
            sec = ELFFile(f).get_section_by_name(".symtab")
            if sec is None:
                return out
            cur_file = None
            for s in sec.iter_symbols():
                t, b = s["st_info"]["type"], s["st_info"]["bind"]
                if t == "STT_FILE":
                    cur_file = s.name
                    continue
                # arm-none-eabi-gcc は static を STT_NOTYPE で出す ($d/$t は ARM のマッピングシンボル)
                data_like = t == "STT_OBJECT" or (t == "STT_NOTYPE" and b == "STB_LOCAL" and s.name
                                                  and not s.name.startswith("$")
                                                  and isinstance(s["st_shndx"], int))
                if data_like:
                    out.append({"name": s.name, "addr": s["st_value"], "size": s["st_size"],
                                "bind": b, "type": t, "file": cur_file if b == "STB_LOCAL" else None})
        return out

    def candidates(self, var: Variable) -> list[dict]:
        """変数に対応しうるシンボル (照合・調査用)"""
        if var.linkage is Linkage.EXTERNAL:
            return [s for s in self.symbols if s["name"] == var.name and s["bind"] != "STB_LOCAL"]
        locals_ = [s for s in self.symbols if s["bind"] == "STB_LOCAL" and s["file"] in (None, var.unit)]
        if var.linkage is Linkage.LOCAL_STATIC:
            pat = re.compile(self.local_static_pattern.format(name=re.escape(var.name)))
            return [s for s in locals_ if pat.fullmatch(s["name"])]
        return [s for s in locals_ if s["name"] == var.name]

    def address_of(self, var: Variable) -> int | None:
        hits = self.candidates(var)
        return hits[0]["addr"] if len(hits) == 1 else None
