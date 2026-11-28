"""DWARF Symbol Resolver: 左辺値 (プリプロセス済みの C 式) をデバッグ情報からアドレス・マスクへ解決するライブラリ。

利用者が使うものはすべてこのパッケージから import できる:

    from dwarf_symbol_resolver import (SymbolResolver, Resolved, Encoding, Linkage, ResolveError,
                           ArmGccDwarfSource, ElfSymtabSource,
                           BracketCommentParser, MonitorFields)

    class MyBracket(BracketCommentParser[MyInfo]):        # T (MyInfo) は利用者が決める
        def build(self, parsed: MonitorFields) -> MyInfo: ...

    resolver = SymbolResolver(ArmGccDwarfSource("app.elf"),
                              address_sources=[ElfSymtabSource("app.elf")],
                              src_dirs=["src"],
                              comment_parsers=[MyBracket()])
    r = resolver.resolve("st.ar[1].bits.level")
    match r.encoding:
        case Encoding.FLOAT: ...

マクロ展開は行わない (呼び出し側でコンパイラの -E を使って展開済みの式を渡す)。

モジュール構成:
    model.py      処理系に依存しない型・変数のモデル (Encoding, Linkage, CType, Variable ...)
    lvalue.py     左辺値の表現 AccessPath と文字列からの変換
    result.py     解決結果 Resolved
    resolver.py   SymbolResolver (AccessPath を model の上でたどる)
    comments/     コメント解析
        base.py         CommentParser[T, P] (parse → extract → build), RegexCommentParser, Sample
        fields.py       dataclass 形式の parsed (MonitorFields)
        formats/        形式ごとのパーサ (1 形式 1 モジュール, __init__.py は自動生成)
        catalog.py      形式の集約・衝突確認 (CATALOG.md を生成)
    sources/      処理系ごとの情報源
        base.py         DebugInfoSource / SymbolAddressSource (Protocol)
        dwarf/common.py DWARF の標準解釈 DwarfSource (フックを上書きして癖を吸収)
        dwarf/<処理系>.py 処理系ごとの DwarfSource (arm_gcc.py など)
        elf_symtab.py   ELF シンボル表
    examples/     利用例 (monitor_info.py: T と build の実装例)
    devtools/     開発用ツール (処理系の検証, DWARF の調査, コメント形式の集約・確認)
"""
from .comments import (CommentParser, KeyValue, MonitorFields, RegexCommentParser, Sample, eval_fraction,
                       parse_first, try_fraction)
from .comments.formats import *  # noqa: F401,F403  (形式ごとのパーサ: BracketCommentParser など)
from .comments.formats import __all__ as _formats_all
from .errors import ResolveError
from .lvalue import AccessPath, parse_lvalue
from .model import (ArrayType, BaseType, CType, Encoding, EnumType, Linkage, Member, PointerType,
                    SourceLoc, StructType, Variable)
from .resolver import SymbolResolver
from .result import Resolved
from .sources import ArmGccDwarfSource, DebugInfoSource, DwarfSource, ElfSymtabSource, SymbolAddressSource

__all__ = [
    # 解決
    "SymbolResolver", "Resolved", "ResolveError", "AccessPath", "parse_lvalue",
    # モデル
    "Encoding", "Linkage", "CType", "BaseType", "EnumType", "PointerType", "StructType", "ArrayType",
    "Member", "Variable", "SourceLoc",
    # 情報源
    "DebugInfoSource", "SymbolAddressSource", "DwarfSource", "ArmGccDwarfSource",
    "ElfSymtabSource",
    # コメント
    "CommentParser", "RegexCommentParser", "KeyValue", "Sample", "MonitorFields", "parse_first",
    "eval_fraction", "try_fraction",
    *_formats_all,
]
