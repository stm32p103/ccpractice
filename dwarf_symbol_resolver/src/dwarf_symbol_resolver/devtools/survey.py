"""ELF / DWARF の特徴を調べて Markdown で出力する (処理系の癖を調べるための調査ツール)。

usage: dsr-dwarf-survey app.elf [--max-items N]
       (または python -m dwarf_symbol_resolver.devtools.survey app.elf)

DwarfSource が前提にしている点 (アドレスの表し方, ビットフィールド属性, ファイル番号, シンボル名) を
中心に, 実際に使われている属性と FORM を列挙する。pyelftools が読めない箇所は例外として報告する。
"""
from __future__ import annotations

import argparse
import collections
import traceback

from elftools.elf.elffile import ELFFile

TAGS = ("DW_TAG_variable", "DW_TAG_member", "DW_TAG_subrange_type", "DW_TAG_enumeration_type",
        "DW_TAG_base_type", "DW_TAG_structure_type", "DW_TAG_union_type", "DW_TAG_array_type",
        "DW_TAG_typedef", "DW_TAG_subprogram")

OPNAMES = {0x03: "DW_OP_addr", 0xA1: "DW_OP_addrx", 0x91: "DW_OP_fbreg", 0x23: "DW_OP_plus_uconst",
           0x0C: "DW_OP_const4u", 0x9F: "DW_OP_stack_value", 0xE0: "DW_OP_GNU_push_tls_address"}


def _op(loc):
    if isinstance(loc, list):
        return OPNAMES.get(loc[0], f"0x{loc[0]:02X}") if loc else "(空)"
    return f"非ブロック({type(loc).__name__})"  # ロケーションリストなど


def survey(elf_path: str, max_items: int = 30) -> list[str]:
    L: list[str] = []
    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        h = elf.header
        L += ["### ELF", "",
              f"- クラス: {elf.elfclass}bit, エンディアン: {'little' if elf.little_endian else 'big'}, "
              f"マシン: {h['e_machine']}",
              "- デバッグ関連セクション: " + ", ".join(
                  f"`{s.name}`" for s in elf.iter_sections() if s.name.startswith((".debug", ".zdebug"))),
              f"- `.symtab`: {'あり' if elf.get_section_by_name('.symtab') else 'なし'}", ""]
        if not elf.has_dwarf_info():
            return L + ["**DWARF がない**"]

        dw = elf.get_dwarf_info()
        attrs: dict[str, collections.Counter] = {t: collections.Counter() for t in TAGS}
        loc_ops = collections.Counter()
        local_vars = collections.Counter()
        bitfield = collections.Counter()
        unknown = collections.Counter()
        errors = []
        cus = []
        try:
            for cu in dw.iter_CUs():
                top = cu.get_top_DIE()
                prod = top.attributes.get("DW_AT_producer")
                name = top.attributes.get("DW_AT_name")
                cus.append(f"`{name.value.decode() if name else '?'}`: v{cu['version']}, "
                           f"address_size={cu['address_size']}, producer=`"
                           f"{prod.value.decode() if prod and isinstance(prod.value, bytes) else prod and prod.value}`")
                for die in cu.iter_DIEs():
                    if die.tag is None:
                        continue
                    if not isinstance(die.tag, str) or not die.tag.startswith("DW_TAG_"):
                        unknown[f"tag {die.tag}"] += 1
                    for an, av in die.attributes.items():
                        if not isinstance(an, str) or "user" in an or an.startswith("DW_AT_0x"):
                            unknown[f"attr {an} ({av.form}) on {die.tag}"] += 1
                        if die.tag in attrs:
                            attrs[die.tag][f"{an}:{av.form}"] += 1
                    if die.tag == "DW_TAG_variable":
                        parent = die.get_parent()
                        where = "関数内" if parent is not None and parent.tag in (
                            "DW_TAG_subprogram", "DW_TAG_lexical_block") else "ファイル"
                        loc = die.attributes.get("DW_AT_location")
                        key = f"{where}: {_op(loc.value) if loc else 'location なし'}"
                        loc_ops[key] += 1
                    if die.tag == "DW_TAG_member" and "DW_AT_bit_size" in die.attributes:
                        kinds = [a for a in ("DW_AT_bit_offset", "DW_AT_data_bit_offset",
                                             "DW_AT_data_member_location", "DW_AT_byte_size")
                                 if a in die.attributes]
                        bitfield[" + ".join(kinds)] += 1
        except Exception as e:  # pyelftools が読めない
            errors.append(f"{type(e).__name__}: {e}\n" + traceback.format_exc(limit=3))

        L += ["### DWARF", ""] + [f"- CU {c}" for c in cus] + [""]
        if errors:
            L += ["**pyelftools での読み込みエラー**", "", "```"] + errors + ["```", ""]
        L += ["#### 変数の DW_AT_location (先頭の命令)", ""] + \
             [f"- {k}: {v} 件" for k, v in loc_ops.most_common()] + [""]
        L += ["#### ビットフィールドの属性の組み合わせ", ""] + \
             ([f"- {k}: {v} 件" for k, v in bitfield.most_common()] or ["- (ビットフィールドなし)"]) + [""]
        if unknown:
            L += ["#### 標準外 (ベンダー拡張) の可能性があるタグ・属性", ""] + \
                 [f"- {k}: {v} 件" for k, v in unknown.most_common(max_items)] + [""]
        L += ["#### タグごとの属性:FORM", ""]
        for t, c in attrs.items():
            if c:
                L.append(f"- `{t}`: " + ", ".join(f"`{k}`" for k in sorted(c)))
        L.append("")

        sec = elf.get_section_by_name(".symtab")
        if sec is not None:
            cur = None
            rows = []
            for s in sec.iter_symbols():
                t, b = s["st_info"]["type"], s["st_info"]["bind"]
                if t == "STT_FILE":
                    cur = s.name
                elif b == "STB_LOCAL" and t in ("STT_OBJECT", "STT_NOTYPE") and s.name and not s.name.startswith(("$", ".")):
                    rows.append(f"`{s.name}` ({t}, file={cur}, 0x{s['st_value']:X})")
            L += ["### ELF シンボル表のローカルシンボル (static 変数の候補)", ""] + \
                 [f"- {r}" for r in rows[:max_items]] + \
                 ([f"- ... ほか {len(rows) - max_items} 件"] if len(rows) > max_items else []) + [""]
    return L


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("--max-items", type=int, default=30)
    a = ap.parse_args(argv)
    print("\n".join(survey(a.elf, a.max_items)))


if __name__ == "__main__":
    main()
