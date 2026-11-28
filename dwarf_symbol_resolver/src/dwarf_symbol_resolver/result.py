"""解決結果"""
from __future__ import annotations

from dataclasses import dataclass, field

from .lvalue import AccessPath
from .model import Encoding, Linkage, Variable


@dataclass
class Resolved[T]:
    """左辺値 1 件の解決結果 (RAM モニタツールに設定する情報)。

    例: st.ar[1].bits.level (unsigned int level:12, ビット 4..15)
        address=0x90F4, size=4, mask=0x0000FFF0, shift=4, bit_size=12
        → 0x90F4 から 32bit 読み, (値 & mask) >> shift が level の値
    """

    path: AccessPath
    """解決した左辺値 (ルート変数名・スコープ・メンバ/インデックスの並び)"""

    address: int
    """モニタツールが読み出す先頭アドレス。
    通常は左辺値そのもののアドレス。ビットフィールドの場合はそれを含む格納単位の先頭アドレス"""

    size: int
    """読み出し幅 (バイト)。通常は sizeof(左辺値)。
    ビットフィールドの場合は宣言型の幅 (unsigned int なら 4)。
    宣言型の格納単位をまたぐ場合は, 範囲を覆う最小の 1/2/4/8 バイト"""

    mask: int | None
    """ビットフィールドの場合のみ。address から size バイト読んだ値 (リトルエンディアンで整数化) に
    対し, 対象ビットを 1 にしたマスク (LSB 基準)。ビットフィールドでなければ None (全ビットが対象)"""

    shift: int | None
    """ビットフィールドの場合のみ。読み出した値の何ビット目から対象が始まるか (= mask の最下位の 1 の位置)"""

    bit_size: int | None
    """ビットフィールドの場合のみ。ビット幅 (宣言の `: N` の N)"""

    ctype: str
    """C の型名 (typedef 名を優先, 例: "volatile short int", "Inner")。
    ルート変数が volatile ならメンバにも "volatile" を付ける"""

    encoding: Encoding | None
    """値の解釈 (Encoding)。基本型でない (構造体・配列・enum・ポインタ) 場合は None"""

    root_address: int
    """ルート変数 (path.root) の先頭アドレス。デバッグ情報のアドレスを優先し, なければ SymbolAddressSource"""

    root_offset: int
    """ルート変数の先頭から address までのバイト数 (address = root_address + root_offset)。
    再ビルドで配置が変わらなければ, 新しい root_address に足すだけでアドレスを再計算できる"""

    linkage: Linkage
    """ルート変数の結合 (Linkage)"""

    comment: T | None
    """宣言のコメントを SymbolResolver に渡した CommentParser[T] で解析した結果。
    どのパーサも合致しなければ None。値の加工 (LSB の差し替えなど) は利用側で行う。
    配列要素の場合は配列の宣言, メンバの場合はメンバの宣言のコメントが対象"""

    comment_src: str | None
    """コメントを探した宣言の位置 ("sample.c:52" など)。ソースが見つからなければ "(ソースなし)" 付き"""

    variable: Variable | None = None
    """ルート変数のモデル (デバッグ用)"""

    notes: list[str] = field(default_factory=list)
    """注意事項 (例: map にシンボルがない, DWARF とシンボル表のアドレスが不一致, 格納単位をまたぐ など)"""
