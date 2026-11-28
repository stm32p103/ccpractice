"""左辺値を model の型情報の上でたどり, アドレス・マスクを求める (処理系に依存しない部分)"""
from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from .comments import CommentParser, extract_comments, parse_first, scan_comments
from .errors import ResolveError
from .lvalue import AccessPath, parse_lvalue
from .model import ArrayType, BaseType, CType, EnumType, SourceLoc, StructType, Variable
from .result import Resolved
from .sources.base import DebugInfoSource, SymbolAddressSource


class SymbolResolver[T]:
    """左辺値 → Resolved[T]。T はコメント解析結果の型 (comment_parsers が返す型)。

    debug_info      : 型・変数の情報源 (処理系に合った DebugInfoSource)
    address_sources : アドレスの補完・照合に使う情報源 (ELF シンボル表など)。先頭ほど優先
    src_dirs        : コメントを読むためのソースの検索先
    comment_parsers : コメント形式ごとのパーサ。先頭ほど優先度が高い (comments.parse_first)
    """

    def __init__(self, debug_info: DebugInfoSource,
                 address_sources: Sequence[SymbolAddressSource] = (),
                 src_dirs: Sequence[str] = (),
                 comment_parsers: Sequence[CommentParser[T, Any]] = ()):
        self.debug_info = debug_info
        self.address_sources = list(address_sources)
        self.src_dirs = list(src_dirs)
        self.comment_parsers = list(comment_parsers)
        self._src_cache: dict[str, list | None] = {}

    @classmethod
    def from_elf(cls, elf_path: str, *, debug_info_cls=None,
                 src_dirs: Sequence[str] = (), comment_parsers: Sequence[CommentParser[T, Any]] = ()):
        """ELF から組み立てる簡易コンストラクタ (アドレスの照合には ELF シンボル表を使う)。

        debug_info_cls : DebugInfoSource のクラス (既定: ArmGccDwarfSource)
        """
        from .sources import ArmGccDwarfSource, ElfSymtabSource
        debug_info = (debug_info_cls or ArmGccDwarfSource)(elf_path)
        return cls(debug_info, [ElfSymtabSource(elf_path)], src_dirs, comment_parsers)

    def close(self):
        close = getattr(self.debug_info, "close", None)
        if close:
            close()

    # ---- 解決
    def parse(self, text: str) -> AccessPath:
        """プリプロセス済みの左辺値式を AccessPath に変換 (enum 定数はデバッグ情報から評価)"""
        return parse_lvalue(text, self.debug_info.enum_value)

    def resolve(self, lhs: str | AccessPath) -> Resolved[T]:
        path = lhs if isinstance(lhs, AccessPath) else self.parse(lhs)
        var = self._find_var(path)
        notes: list[str] = []
        t: CType = var.type
        volatile = t.volatile
        offset = 0
        bitpos = bit_size = None
        decl: SourceLoc | None = var.decl
        arr: ArrayType | None = None  # たどり途中の配列
        dims: list[int | None] = []    # その残り次元

        for kind, v in path.steps:
            if bitpos is not None:
                raise ResolveError("ビットフィールドの先はたどれない")
            if kind == "index":
                if arr is None:
                    if not isinstance(t, ArrayType):
                        raise ResolveError(f"配列ではない型に [] : {t.name}")
                    arr, dims = t, list(t.dims)
                n = dims[0]
                if n is not None and not 0 <= v < n:
                    raise ResolveError(f"インデックス範囲外: [{v}] (要素数 {n})")
                stride = arr.elem.size
                for d in dims[1:]:
                    stride *= d
                offset += v * stride
                dims = dims[1:]
                if not dims:
                    t, arr = arr.elem, None
                    volatile |= t.volatile
            else:
                if arr is not None:
                    raise ResolveError("配列の次元が足りない")
                if not isinstance(t, StructType):
                    raise ResolveError(f"構造体/共用体ではない型に .{v} : {t.name}")
                m = t.members.get(v)
                if m is None:
                    raise ResolveError(f"メンバがない: .{v} ({t.name})")
                decl = m.decl or decl
                if m.bit_size is None:
                    offset += m.offset
                else:
                    bitpos, bit_size = offset * 8 + m.bit_pos, m.bit_size
                t = m.type
                volatile |= t.volatile

        if arr is not None:
            notes.append("配列全体を指している")
            size = arr.elem.size
            for d in dims:
                size *= d
            ctype = arr.name
            mask = shift = None
            unit_off = offset
        elif bitpos is None:
            size, ctype, mask, shift, unit_off = t.size, t.name, None, None, offset
        else:
            size, ctype = t.size, t.name               # 宣言型の幅でアクセス
            ubits = size * 8
            unit_start = (bitpos // ubits) * ubits
            if bitpos + bit_size > unit_start + ubits:
                unit_start = (bitpos // 8) * 8         # 格納単位をまたぐ → 最小のバイト範囲
                nbytes = (bitpos + bit_size - unit_start + 7) // 8
                size = 1 << (nbytes - 1).bit_length()
                notes.append("宣言型の格納単位をまたぐビットフィールド")
            shift = bitpos - unit_start
            mask = ((1 << bit_size) - 1) << shift
            unit_off = unit_start // 8

        if volatile and "volatile" not in ctype:
            ctype = "volatile " + ctype                # ルート変数の volatile はメンバにも及ぶ
        encoding = t.encoding if arr is None and isinstance(t, (BaseType, EnumType)) else None
        root_addr = self._root_address(var, notes)
        comment, csrc = self._comment(decl)
        return Resolved(path, root_addr + unit_off, size, mask, shift, bit_size, ctype, encoding,
                        root_addr, unit_off, var.linkage, comment, csrc, var, notes)

    def _find_var(self, path: AccessPath) -> Variable:
        cands = self.debug_info.find_variables(path.root)
        scope = list(path.scope)
        if scope and os.path.splitext(scope[0])[1] in (".c", ".h", ".cpp"):
            f = scope.pop(0)
            cands = [c for c in cands if c.unit == f]
        cands = [c for c in cands if c.func == (scope[0] if scope else None)]
        defs = [c for c in cands if c.address is not None] or cands
        if not defs:
            raise ResolveError(f"変数が見つからない: {path.root} (scope={path.scope})")
        if len(defs) > 1:
            where = ", ".join(f"{c.unit}::{c.func or ''}" for c in defs)
            raise ResolveError(f"同名の変数が複数: {path.root} ({where}) — scope:: で指定")
        return defs[0]

    def _root_address(self, var: Variable, notes: list[str]) -> int:
        """デバッグ情報のアドレスを優先し, なければ address_sources の先頭から。全情報源と照合する"""
        addr = var.address
        for src in self.address_sources:
            a = src.address_of(var)
            if a is None:
                notes.append(f"{src.name} で特定できず")
            elif addr is None:
                addr = a
            elif a != addr:
                notes.append(f"{src.name} 0x{a:X} とデバッグ情報 0x{addr:X} が不一致")
        if addr is None:
            raise ResolveError(f"アドレス不明: {var.name}")
        return addr

    # ---- コメント
    def _comment(self, decl: SourceLoc | None) -> tuple[T | None, str | None]:
        if decl is None:
            return None, None
        fname = os.path.basename(decl.file)
        comments = self._source_comments(fname)
        if comments is None:
            return None, f"{fname}:{decl.line}(ソースなし)"
        return parse_first(self.comment_parsers, extract_comments(comments, decl.line)), f"{fname}:{decl.line}"

    def _source_comments(self, fname: str):
        if fname not in self._src_cache:
            self._src_cache[fname] = None
            for d in self.src_dirs:
                p = os.path.join(d, fname)
                if os.path.exists(p):
                    with open(p, encoding="utf-8", errors="replace") as f:
                        self._src_cache[fname] = scan_comments(f.read())
                    break
        return self._src_cache[fname]
