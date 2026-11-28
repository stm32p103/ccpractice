---
name: dwarf-adapter
description: 新しい処理系 (コンパイラ/リンカ) 向けに dwarf_symbol_resolver の DWARF 解析クラスを作る。利用者にコンパイル・リンクのコマンドを問い合わせ、verification/sample.c を実際にビルドできることを確かめてから、DWARF の癖を調べ、src/dwarf_symbol_resolver/sources/dwarf/<処理系>.py を生成し、コンパイラの正解と一致するまで検証する。「処理系を追加」「Green Hills に対応」「DWARF の癖を吸収」「アダプタを作る」と言われたときに使う。
---

# DWARF 解析クラス (処理系アダプタ) の作成

左辺値解決ライブラリ DWARF Symbol Resolver (`dwarf_symbol_resolver`) (`src/dwarf_symbol_resolver/`) に、新しい処理系の DWARF 解析クラスを追加する。
成果物は次の 2 つ。

- `src/dwarf_symbol_resolver/sources/dwarf/<name>.py` … `DwarfSource` を継承したクラス (arm_gcc.py と同じ階層)
- `verification/toolchains/<name>.json` … その処理系のビルドコマンドと検証設定

**ビルドが通ることを確認するまで、コード (アダプタ) は生成しない。**

## 前提

- 作業ディレクトリはリポジトリのルート (`pyproject.toml` のある場所)。`pip install -e .` でインストール済みであること (`dsr-*` コマンドが使える)
- Python から `pyelftools` を import できること (できなければ `pip install pyelftools` を利用者に依頼)
- 参考にするファイル:
  - `src/dwarf_symbol_resolver/sources/dwarf/common.py` … 標準 DWARF の解釈とフック一覧
  - `src/dwarf_symbol_resolver/sources/dwarf/arm_gcc.py` … 完成済みのアダプタの例
  - `verification/toolchains/arm_gcc.json` … 設定の例
  - `src/dwarf_symbol_resolver/devtools/verify_toolchain.py` 冒頭 … 設定ファイルの項目の説明

## 手順

### 1. 利用者への問い合わせ

次を利用者に尋ねる。コマンドは「普段ターミナルで打つ形」で受け取り、こちらで JSON の配列に変換する。
分からない項目は「不明」でよい (後の手順で調べる)。

1. 処理系の名前 (ファイル名・クラス名に使う。例 `ghs_rh850` → `GhsRh850DwarfSource`)
2. プリプロセスだけを行うコマンド (例 `ccrh850 -E file.c -o file.i`)
3. コンパイルのコマンド (DWARF を出すオプションを含むこと)
4. リンクのコマンド (必要ならリンカスクリプト・スタートアップ)
5. 試したいバリアント (DWARF バージョン違いなど。なければ 1 つ)
6. 関数内 static のシンボル名の規則 (不明なら手順 4 で調べる)

コマンドを JSON にするときの置換文字列:

| 置換 | 意味 |
|---|---|
| `{src}` | 入力の C ファイル (絶対パスに置き換わる) |
| `{out}` | プリプロセス結果の出力ファイル |
| `{obj}` | オブジェクトファイル |
| `{elf}` | リンク結果 (ELF) |
| `"{variant_flags}"` | 配列の 1 要素として書くと、バリアントのオプション列に展開される |

PowerShell の `,` 問題などを避けるため、コマンドは必ず引数ごとの配列で書く。

### 2. 設定ファイルの作成

`verification/toolchains/<name>.json` を作る。この時点では `debug_info` は汎用の `DwarfSource` にする。

```json
{
  "name": "<name>",
  "description": "<処理系とターゲットの説明>",
  "variants": {"default": []},
  "preprocess": ["<cc>", "-E", "{src}", "-o", "{out}"],
  "compile":    ["<cc>", "...", "{variant_flags}", "-c", "{src}", "-o", "{obj}"],
  "link":       ["<cc or ld>", "...", "-o", "{elf}", "{obj}"],
  "debug_info": "dwarf_symbol_resolver.sources.dwarf.common:DwarfSource",
  "local_static_pattern": "{name}\\.\\d+",
  "typeof": "__typeof__",
  "remarks": {}
}
```

出力先は既定で `verification/results/<name>/<variant>/`。

### 3. ビルド確認 (ここを通過するまでコードを書かない)

```
dsr-verify-toolchain verification/toolchains/<name>.json --build-only
```

- 成功: `ビルド成功` と実行したコマンドが表示される。利用者に結果を伝えて次へ進む
- 失敗: エラーメッセージを利用者に見せ、原因の見立てと修正案を示す。
  **コマンドの修正は利用者に確認してから**設定に反映し、再実行する。よくある原因:
  - エントリポイント・スタートアップがない (`sample.c` は `_start` を定義している。処理系のスタートアップと衝突する場合は外す、または不要にするオプションを尋ねる)
  - リンカスクリプト・メモリ配置の指定が必要
  - `void main(void)` が警告/エラーになる (警告を抑止するオプションを尋ねる)
  - インクルードパス・ライセンスなどの環境の問題 (利用者の環境でしか直せないので、状況を伝えて待つ)
- `sample.c` や `lvalues.txt` を処理系に合わせて書き換えない。どうしても必要なら理由を説明して利用者の了承を得る

### 4. DWARF の調査

```
dsr-dwarf-survey verification/results/<name>/<variant>/app.elf
```

出力を読み、`common.py` の `DwarfSource` の前提と違う点を洗い出す。確認項目:

| 項目 | DwarfSource の前提 | 違う場合に上書きするフック |
|---|---|---|
| pyelftools の読み込みエラー | なし | (フックでは直せない。手順 8 へ) |
| エンディアン | little (big はビットフィールドで未対応) | `bitfield_pos`, `variable_address` |
| 変数の DW_AT_location | `DW_OP_addr` 1 命令 | `variable_address`, `is_static_storage` |
| 関数内 static | 関数の DIE の子に、固定アドレス付きで出る | `is_static_storage`, `linkage_of` |
| ビットフィールド | `DW_AT_data_bit_offset`、または `DW_AT_bit_offset` (+ `DW_AT_byte_size`, `DW_AT_data_member_location`) の標準の意味 | `bitfield_pos` |
| DW_AT_data_member_location | 定数、または `DW_OP_plus_uconst` のブロック | `member_offset` |
| DW_AT_encoding | 標準の DW_ATE 値 | `base_encoding` |
| enum の符号 | 元の整数型、なければ値の範囲 | `enum_encoding` |
| DW_AT_decl_file | v5 は 0 始まり、v4 以前は 1 始まり | `decl` |
| ベンダー拡張の属性 | 無視してよい | 必要なものだけ各フックで読む |
| static のシンボル名 | `name.N` (GCC) | 設定の `local_static_pattern` |

### 5. 汎用クラスでの検証 (基準)

```
dsr-verify-toolchain verification/toolchains/<name>.json
```

`verification/results/<name>/<variant>/result.md` の表で `✗` の行と「備考」を確認する。
`verify.c` のビルドに失敗した場合は、`typeof` のキーワード (`typeof`, `__typeof` など) や、
`__attribute__((used))`・指示付き初期化子が使えるかを利用者に確認する。

全件が一致すれば、癖はない。手順 6 は「フックを上書きしないクラス」を作るだけでよい (arm_gcc.py と同じ形)。

### 6. アダプタの生成

`src/dwarf_symbol_resolver/sources/dwarf/<name>.py` を作る。

```python
"""<処理系> 向けの DWARF 解析。

検証: <処理系のバージョン>, <オプション> (verification/sample.c + verification/lvalues.txt,
     結果は verification/results/<name>/<variant>/result.md)

観察された特徴:
- <手順 4・5 で分かった癖と、それをどう吸収したか>
"""
from __future__ import annotations

from .common import DwarfSource


class <Name>DwarfSource(DwarfSource):
    """<処理系> の DWARF。<上書きしたフックの要約>"""

    toolchain = "<処理系の表示名>"

    # 必要なフックだけを上書きする (例)
    # def bitfield_pos(self, die, unit_size: int) -> int:
    #     ...
```

続けて、次の 3 か所の公開一覧に追加する (利用者が 1 回の import で使えるようにする)。

- `src/dwarf_symbol_resolver/sources/dwarf/__init__.py` (import と `__all__`)
- `src/dwarf_symbol_resolver/sources/__init__.py` (import と `__all__`)
- `src/dwarf_symbol_resolver/__init__.py` (import と `__all__`、冒頭の docstring のモジュール構成)

設定ファイルの `debug_info` を `dwarf_symbol_resolver.sources.dwarf.<name>:<Name>DwarfSource` に、
シンボル名の規則が違えば `local_static_pattern` を更新する。

守ること:
- 上書きは**フックだけ**。`common.py` を処理系の都合で書き換えない
  (標準の DWARF の解釈そのものが誤っていた場合だけ、理由を説明したうえで直し、`verification/toolchains/arm_gcc.json` の検証も再実行して壊れていないことを確かめる)
- フックの戻り値は `model.py` 冒頭の定義に正規化する (オフセットはバイト、`bit_pos` は構造体先頭からのリトルエンディアン式のビット位置)

### 7. 再検証

```
dsr-verify-toolchain verification/toolchains/<name>.json
```

正常系がすべて `✓` (関数内 static は `△`)、エラー期待がすべてエラーになるまで手順 6 と 7 を繰り返す。
直らない項目は、原因の見立てを付けて利用者に報告する (無理に合わせない)。

最後に、分かった癖を設定の `remarks` に書き、もう一度実行して `result.md` に反映する。

### 8. pyelftools で読めない場合

手順 4 で読み込みエラーが出た場合は、フックでは対処できない。作業を止めて利用者に次を報告する。

- エラーの内容 (どのセクション・FORM・属性で失敗したか)
- 対応案: ① 処理系のオプションで標準的な DWARF を出せないか確認する ② `DebugInfoSource` Protocol (`sources/base.py`) を別の方法 (別のライブラリ、処理系付属のダンプツールの出力の解析など) で実装する

## 完了時の報告

利用者に次を伝える。

- 作成・変更したファイル
- 検証結果 (バリアントごとの一致件数) と `result.md` へのリンク
- 見つかった癖と、それをどのフックで吸収したか
- 未解決の項目と、その理由
