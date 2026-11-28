"""処理系に依存しない型・変数のモデル。

DebugInfoSource (DWARF など) はデバッグ情報をこのモデルに変換して返す。
処理系ごとの癖 (ビットフィールド位置の数え方, アドレスの表し方 など) は変換時に吸収し,
このモデルの値は常に下記の意味に正規化されている。

- オフセット・サイズはバイト単位
- Member.bit_pos は「構造体先頭からのビット位置」で, ビット k はメモリ上の
  (k // 8) バイト目の (k % 8) ビット目 (LSB = 0) を指す (リトルエンディアンの数え方)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Encoding(Enum):
    """size バイトのデータをどう解釈するか。

    幅は Resolved.size (ビットフィールドなら bit_size) で判断する。型名 (long, double など) では判断しない。
    """

    SIGNED = "signed"
    """符号付き整数 (signed char を含む)。ビットフィールドなら bit_size ビットで符号拡張する"""
    UNSIGNED = "unsigned"
    """符号なし整数 (unsigned char を含む)"""
    FLOAT = "float"
    """浮動小数点 (size=4 なら単精度, 8 なら倍精度)"""
    BOOL = "bool"
    """真偽値 (_Bool)"""


class Linkage(Enum):
    """変数の結合 (どこから見える変数か)"""

    EXTERNAL = "external"
    """外部結合 (グローバル変数)"""
    INTERNAL = "internal"
    """内部結合 (ファイル内 static)。同名がほかのファイルにあれば `ファイル名::変数名` で区別する"""
    LOCAL_STATIC = "local-static"
    """関数内 static。`関数名::変数名` で指定する。シンボル名はコンパイラが付け替える (GCC: name.N)"""


@dataclass(frozen=True)
class SourceLoc:
    """宣言の位置"""

    file: str
    """ファイル名 (デバッグ情報に記録された名前。ディレクトリを含む場合がある)"""
    line: int
    """行番号 (1 始まり)"""

    def __str__(self):
        return f"{self.file}:{self.line}"


# ---------------------------------------------------------------- 型

@dataclass(eq=False)
class BaseType:
    """基本型 (整数・浮動小数点・bool)"""

    name: str
    """表示用の型名 (typedef 名を優先, 修飾子を含む。例 "volatile short int", "uint8_t")"""
    volatile: bool
    size: int
    encoding: Encoding | None


@dataclass(eq=False)
class EnumType:
    """列挙型"""

    name: str
    volatile: bool
    size: int
    encoding: Encoding | None
    """値の解釈 (元になる整数型, または列挙子の値の範囲から決める)"""
    enumerators: dict[str, int] = field(default_factory=dict)


@dataclass(eq=False)
class PointerType:
    """ポインタ (左辺値をたどる対象にはしない。モニタ対象としては size バイトのアドレス値)"""

    name: str
    volatile: bool
    size: int


@dataclass(eq=False)
class StructType:
    """構造体・共用体"""

    name: str
    volatile: bool
    size: int
    is_union: bool
    members: dict[str, Member] = field(default_factory=dict)


@dataclass(eq=False)
class ArrayType:
    """配列 (多次元配列は 1 つの ArrayType で dims に全次元を持つ)"""

    name: str
    volatile: bool
    elem: CType
    """要素の型"""
    dims: list[int | None]
    """各次元の要素数 (外側から)。不明 (extern int a[]; など) は None"""

    @property
    def size(self) -> int | None:
        n = self.elem.size
        for d in self.dims:
            if d is None or n is None:
                return None
            n *= d
        return n


CType = BaseType | EnumType | PointerType | StructType | ArrayType


@dataclass(eq=False)
class Member:
    """構造体・共用体のメンバ"""

    name: str
    type: CType
    offset: int
    """構造体先頭からのバイトオフセット。ビットフィールドの場合は bit_pos // 8 (参考値)"""
    bit_pos: int | None = None
    """ビットフィールドの場合のみ。構造体先頭からのビット位置 (モジュール冒頭の定義に正規化済み)"""
    bit_size: int | None = None
    """ビットフィールドの場合のみ。ビット幅"""
    decl: SourceLoc | None = None


# ---------------------------------------------------------------- 変数

@dataclass(eq=False)
class Variable:
    """静的なアドレスを持つ変数 (グローバル, ファイル内 static, 関数内 static)"""

    name: str
    """ソース上の変数名"""
    linkage: Linkage
    unit: str
    """定義されている翻訳単位のファイル名 (ディレクトリなし, 例 "sample.c")"""
    func: str | None
    """関数内 static の場合の関数名"""
    type: CType
    address: int | None
    """デバッグ情報から得たアドレス。得られなければ None (SymbolAddressSource で補う)"""
    decl: SourceLoc | None = None
