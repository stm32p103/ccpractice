---
name: comment-parser
description: 利用者が示したソースコードの抜粋 (コメント付きの宣言) をもとに、dwarf_symbol_resolver の新しいコメントパーサ (コメント形式) を作る。判定用の正規表現を提案し、既存の形式と衝突しないことを確かめ、parsed の形 (Key-Value か dataclass) を利用者に確認してから src/dwarf_symbol_resolver/comments/formats/<形式>.py を生成する。「コメントの形式を追加」「このコメントを読めるようにして」「コメントパーサを作って」と言われたときに使う。
---

# コメントパーサ (コメント形式) の作成

dwarf_symbol_resolver のコメント解析は 2 段階になっている (`src/dwarf_symbol_resolver/comments/base.py`)。

```
parse(comment: str) -> T | None
    1. extract(comment) -> P | None   形式の判定と項目の抽出 … このスキルが作る (ライブラリ側)
    2. build(parsed: P) -> T          parsed から T を作る    … パッケージの利用者が自ツールで実装する
```

- P (parsed) は Key-Value 形式 (`KeyValue = dict[str, str]`) か dataclass (`comments/fields.py`)
- T は利用者が決めるので、このスキルでは作らない。生成するクラスは `build` を抽象のまま残す
- 形式は `RegexCommentParser[T, P]` を継承し、`pattern` (判定・抽出の正規表現。コメント全体に fullmatch)、
  `samples` (サンプルと期待する parsed)、`to_parsed` (合致結果 → parsed) を持つ
- 参考: `comments/formats/bracket.py` (dataclass の例)、`comments/formats/key_value.py` (Key-Value の例)

作業ディレクトリはリポジトリのルート (`pyproject.toml` のある場所)。`pip install -e .` でインストール済みであること (`dsr-*` コマンドが使える)

## 手順

### 1. 抜粋を受け取る

利用者に、その形式のコメントが書かれたソースの抜粋をいくつか示してもらう (まだなら依頼する)。

- 宣言とコメントを含むコード片のまま受け取ってよい。項目の有無が違う例 (LSB なし、説明なし など) も含めてもらう
- 抜粋はスクラッチパッドにファイルとして保存する (1 抜粋 1 ファイル。`dsr-comment-check` に渡す)
- 形式の名前 (モジュール名・クラス名に使う。例 `at_tag` → `AtTagCommentParser`) を尋ねる

### 2. 項目の読み取りを確認する

抜粋のコメントから、どの部分が何の項目かを読み取って表にし、利用者に確認する。

| 抜粋 | 単位 | LSB | オフセット | 説明 | その他 |
|---|---|---|---|---|---|

読み取りに迷う部分 (区切り記号、省略時の扱い、複数行コメント) は推測で決めず尋ねる。

### 3. parsed の形を決める

利用者に次を尋ねる。

1. parsed を **Key-Value** にするか **dataclass** にするか
   - 既存の dataclass (`comments/fields.py` の `MonitorFields` など) と同じ項目なら、それを再利用すると
     利用者の `build` を形式間で共有できることを伝える
2. dataclass の場合: **どの項目をどの属性名にするか** (既存の dataclass を使う場合も、項目と属性の対応を確認する)
3. Key-Value の場合: キーの名前 (抜粋の表記のままか、正規化するか)

値は加工せず文字列のまま parsed に入れる (数値化は利用者の `build` の役割。`try_fraction` が使える)。

### 4. 正規表現を提案する

- 項目ごとに名前付きグループ `(?P<名前>...)` を使う。グループ名は parsed の属性名 (キー) に合わせる
- コメント記号 (`/*` `*/` `//` `///<` など) を含めた**コメント全体**に fullmatch する形にする (前後の空白は除去される)
- **この形式だけが持つ特徴** (先頭の記号やキーワード) を必ず含め、ほかの形式と区別できるようにする。
  何にでも合致する正規表現 (例 `/\*(?P<description>.*)\*/`) は不可
- 提案した正規表現を、次の手順の確認結果と一緒に示す

### 5. 既存の形式との衝突を確認する (衝突は許容しない)

まず comment-parser-catalog スキルの手順で一覧を最新にする (`python src/dwarf_symbol_resolver/devtools/comment_catalog.py --write`)。
次に候補を確認する。

```
dsr-comment-check --pattern "<正規表現>" --excerpt <抜粋1> --excerpt <抜粋2> ... [--flags S]
```

出力の確認点:

- **抜粋のコメントへの合致**: 形式のコメントがすべて `○` で、抽出された項目が手順 2 の表と一致すること。
  形式でないコメント (普通のコメント) は `×` であること
- **衝突 (a)**: 既存の形式が抜粋のコメントに合致した
- **衝突 (b)**: 候補が既存の形式のサンプルに合致した

衝突があった場合:

1. `src/dwarf_symbol_resolver/comments/CATALOG.md` から、衝突した形式の正規表現とサンプルを取り出す
2. 抜粋のコメントと既存のサンプルを並べ、違いを示す
3. **回避できる特徴があるか** (コメント記号の違い、先頭の記号・キーワード、項目の並び・区切りなど) を示し、
   正規表現の更新案を出す。更新するのは候補・既存の形式のどちらか (または両方)
4. どの案にするかを**利用者に判断してもらう**。回避できる特徴がなければ、その旨を伝え、
   形式の書き方を揃える (ソース側を直す) などの選択肢も示す
5. 既存の形式の pattern を更新する案なら、`--exclude <既存の形式のクラス名>` を付けて更新案の pattern も確認する

衝突が 0 件で、抜粋のコメントの抽出結果が正しくなるまで、手順 4〜5 を繰り返す。

### 6. 形式のモジュールを生成する

`src/dwarf_symbol_resolver/comments/formats/<name>.py` を作る。

```python
"""<形式の短い説明>"""
from __future__ import annotations

import re

from ..base import RegexCommentParser, Sample          # Key-Value なら KeyValue も import
from ..fields import <Parsed>                           # dataclass の場合


class <Name>CommentParser[T](RegexCommentParser[T, <Parsed または KeyValue>]):
    """<書式の説明 (例を含む)>

    判定の特徴: <ほかの形式と区別する特徴>
    """

    pattern = re.compile(r"<手順 5 で確定した正規表現>", re.S)

    samples = (
        Sample("<抜粋のコメント>", <期待する parsed>, "<抜粋の出典>"),
        ...
    )

    @classmethod
    def to_parsed(cls, m: re.Match[str]) -> <Parsed> | None:
        ...
```

- `samples` には利用者の抜粋のコメントを**すべて**入れ、`expected` (期待する parsed) を書く
- 新しい dataclass が必要なら `comments/fields.py` に追加し、`comments/__init__.py` と `src/dwarf_symbol_resolver/__init__.py` の
  import と `__all__` にも加える
- 既存の形式の pattern を更新した場合は、そのモジュールの `samples` も見直す (衝突の原因になったサンプルは消さない)

### 7. 集約と最終確認

comment-parser-catalog スキルの手順で再集約する。

```
python src/dwarf_symbol_resolver/devtools/comment_catalog.py --write
```

全形式が `OK` で、衝突が 0 件であることを確認する。`formats/__init__.py` は自動生成なので手で編集しない。

### 8. 利用者への報告

- 作成・変更したファイル
- 確定した正規表現と、抜粋ごとの抽出結果
- 衝突の確認結果 (あった場合は、どう回避したか)
- 利用者が自ツールで書く `build` の例 (T は利用者のもの):

  ```python
  from dwarf_symbol_resolver import <Name>CommentParser, <Parsed>

  class My<Name>(<Name>CommentParser[MyInfo]):
      def build(self, parsed: <Parsed>) -> MyInfo:
          return MyInfo(...)

  resolver = SymbolResolver(..., comment_parsers=[My<Name>(), ...])   # 先頭ほど優先
  ```

  `src/dwarf_symbol_resolver/examples/monitor_info.py` に、既存の形式で `build` を実装した例がある
