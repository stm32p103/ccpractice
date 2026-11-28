"""処理系ごとに差し替える部分のインターフェース。

- DebugInfoSource     : 型と変数の情報 (DWARF など) を model の形で返す
- SymbolAddressSource : 変数のアドレスを別の情報源 (ELF シンボル表など) から返す。
                        デバッグ情報にアドレスがない場合の補完と, 照合に使う
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..model import Variable


@runtime_checkable
class DebugInfoSource(Protocol):
    """デバッグ情報から型・変数を得る。

    実装は処理系ごとの癖を吸収し, model モジュール冒頭の定義に正規化した値を返すこと。
    """

    def find_variables(self, name: str) -> list[Variable]:
        """名前が一致する, 静的なアドレスを持つ変数をすべて返す
        (別ファイルの同名 static, 関数内 static を含む。自動変数は含めない)。
        宣言だけで定義のない変数 (extern 宣言) は含めないか, address=None で返す"""
        ...

    def enum_value(self, name: str) -> int | None:
        """列挙子の値 (インデックス式の評価に使う)。なければ None"""
        ...

    def describe(self) -> str:
        """情報源の説明 (ログ・注意事項用。例 "DWARF v4 (arm-none-eabi-gcc)")"""
        ...


@runtime_checkable
class SymbolAddressSource(Protocol):
    """変数のアドレスを返す"""

    name: str
    """情報源の名前 (注意事項に使う。例 "ELF シンボル表")"""

    def address_of(self, var: Variable) -> int | None:
        """変数のアドレス。この情報源で見つからなければ None"""
        ...
