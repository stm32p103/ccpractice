# 処理系・コメント形式への適合

処理系 (DWARF の癖) とコメント形式は、利用現場ごとに違います。どちらも「中核を変えずに、決まった場所へ追加する」方式で、
手順は Claude Code のスキル (`.claude/skills/`) にまとめてあります。スキルを使わずに手で行う場合も、同じ手順と規則に従ってください。

## A. 処理系 (DWARF) への適合 — スキル `dwarf-adapter`

### 成果物

- `src/dwarf_symbol_resolver/sources/dwarf/<name>.py` … `DwarfSource` を継承したクラス (`arm_gcc.py` と同じ階層)
- `verification/toolchains/<name>.json` … ビルドコマンドと検証の設定

### 手順の要点

1. **問い合わせ**: 処理系の名前、プリプロセス・コンパイル・リンクのコマンド (DWARF を出すオプションを含む)、
   バリアント (DWARF のバージョン違いなど)、関数内 static のシンボル名の規則を利用者に尋ねる。
   コマンドは引数ごとの配列にする (`{src} {out} {obj} {elf}` と `"{variant_flags}"` を置換)
2. **設定の作成**: `debug_info` は最初は汎用の `dwarf_symbol_resolver.sources.dwarf.common:DwarfSource`
3. **ビルドの確認**: `dsr-verify-toolchain verification/toolchains/<name>.json --build-only`。
   **通るまでコードを生成しない**。失敗したら原因と修正案を示し、利用者の確認を取ってからコマンドを直す
4. **調査**: `dsr-dwarf-survey verification/results/<name>/<variant>/app.elf` で、
   アドレスの表し方、ビットフィールドの属性、FORM、ベンダー拡張、static のシンボル名を確認する
5. **汎用クラスでの検証**: `dsr-verify-toolchain verification/toolchains/<name>.json` の `result.md` で ✗ の行を確認する
6. **クラスの生成**: 必要なフックだけを上書きし (フックの一覧は 03)、説明文に検証条件と観察した癖を書く。
   公開一覧 (`sources/dwarf/__init__.py`、`sources/__init__.py`、パッケージの `__init__.py`) に追加し、
   設定の `debug_info` を新しいクラスにする
7. **再検証**: すべて一致するまで 6〜7 を繰り返す。分かった癖は設定の `remarks` に書き、`result.md` に反映する
8. **pyelftools で読めない場合**: フックでは直せない。作業を止め、処理系のオプションで標準的な DWARF を出せないか、
   または `DebugInfoSource` を別の方法で実装するかを利用者に相談する

### 規則

- `common.py` を処理系の都合で書き換えない (原則 III)
- `verification/sample.c` と `lvalues.txt` を処理系に合わせて書き換えない。検証項目を増やすのはよい (全処理系で再検証する)
- 検証コード (`verify.c`) は `__typeof__`、`__attribute__((used))`、指示付き初期化子を使う。
  使えない処理系は設定の `typeof` で代替のキーワードを指定するか、利用者に相談する

### 設定ファイルの例 (`verification/toolchains/arm_gcc.json` の要約)

```json
{
  "name": "arm_gcc",
  "variants": {"v2": ["-gdwarf-2"], "v3": ["-gdwarf-3"], "v4": ["-gdwarf-4"], "v5": ["-gdwarf-5"]},
  "preprocess": ["arm-none-eabi-gcc", "-E", "-P", "{src}", "-o", "{out}"],
  "compile": ["arm-none-eabi-gcc", "-mcpu=cortex-m4", "-O0", "-g3", "-std=gnu11", "{variant_flags}", "-w", "-c", "{src}", "-o", "{obj}"],
  "link": ["arm-none-eabi-gcc", "-mcpu=cortex-m4", "-nostdlib", "-Wl,-e,0", "-o", "{elf}", "{obj}"],
  "debug_info": "dwarf_symbol_resolver.sources.dwarf.arm_gcc:ArmGccDwarfSource",
  "local_static_pattern": "{name}\\.\\d+",
  "typeof": "__typeof__",
  "remarks": {"*": ["..."], "v2": ["..."]}
}
```

### Green Hills (RH850) について分かっていること

- 標準のデバッグ情報は独自形式。`-dual_debug` (版により `-G -dual_debug`) で ELF に DWARF が入る
  (Lauterbach のサポート記事による。Green Hills のマニュアルでは未確認)
- Renesas の e² studio が Green Hills の ELF/DWARF をデバッグできることから、他社ツールが読める DWARF が出ると見込まれる
- 実物では未検証。最初の確認点は `dsr-dwarf-survey` で、変数の `DW_AT_location` の形式とビットフィールドの属性を見ること

## B. コメント形式への適合 — スキル `comment-parser` / `comment-parser-catalog`

### 仕組み

```
parse(comment: str) -> T | None
    extract(comment) -> P | None   形式の判定と項目の抽出 … 形式ごとのクラス (ライブラリ側)
    build(parsed: P) -> T          parsed から T を作る    … 利用者が実装
```

- 形式は `RegexCommentParser[T, P]` を継承し、`pattern` (コメント全体に fullmatch する正規表現。前後の空白は除く)、
  `samples` (`Sample(コメント, 期待する parsed, 出典)`)、`to_parsed` (合致結果 → parsed) を持つ
- P (parsed) は Key-Value (`KeyValue = dict[str, str]`) か dataclass (`comments/fields.py`)。値は加工しない文字列
- コメント文字列はコメント記号 (`/*` `*/` `//` `///<`) を含んだまま渡す。記号の違いで形式を見分けるため
- **衝突**: ある形式の `pattern` がほかの形式のサンプルに合致すること。許容しない (原則 IV)

### 既存の形式

| クラス | 書式 | parsed |
|---|---|---|
| `BracketCommentParser` | `/* [単位] LSB=式 OFS=式 説明 */` または `// [単位] ...` | `MonitorFields(unit, lsb, offset, description)` |
| `KeyValueCommentParser` | `///< unit: 単位, lsb: 式, ofs: 式, desc: 説明` | `KeyValue` (キーは小文字) |

一覧の最新は `src/dwarf_symbol_resolver/comments/CATALOG.md` (自動生成)。

### 新しい形式の追加 (`comment-parser`)

1. 利用者からソースの抜粋 (コメント付きの宣言) を受け取り、ファイルに保存する
2. どの部分が何の項目かを表にして利用者に確認する (迷う点は推測しない)
3. parsed を Key-Value にするか dataclass にするか、dataclass ならどの項目をどの属性名にするかを尋ねる
   (既存の dataclass と同じ項目なら再利用を勧める。利用者の `build` を形式間で共有できる)
4. 名前付きグループを使った正規表現を提案する。**その形式だけが持つ特徴** (先頭の記号やキーワード) を必ず含める
5. 一覧を最新にしてから候補を確認する:
   ```
   python src/dwarf_symbol_resolver/devtools/comment_catalog.py --write
   dsr-comment-check --pattern "<正規表現>" --excerpt <抜粋1> --excerpt <抜粋2> [--flags S]
   ```
   衝突があれば、CATALOG.md の既存のサンプルと抜粋を並べて違いを示し、回避できる特徴と正規表現の更新案を出して
   **利用者に判断してもらう**。衝突 0 件・抽出結果が正しくなるまで繰り返す
6. `comments/formats/<name>.py` を生成する。抜粋のコメントはすべて期待値付きのサンプルとして入れる
7. 再集約して、全形式 OK・衝突 0 件を確認する

### 一覧の再生成 (`comment-parser-catalog`)

```
python src/dwarf_symbol_resolver/devtools/comment_catalog.py --write
```

- `formats/__init__.py` (import と `ALL_FORMATS`) と `CATALOG.md` を再生成し、自己テストと衝突確認を行う
- `formats/__init__.py` は手で編集しない。形式の追加・削除・改名の後は必ず再生成する
- 形式のモジュールを削除・改名した直後は、古い `__init__.py` のせいでパッケージを import できないので、
  `dsr-comment-catalog` ではなく上のファイル指定の形で実行する
- ファイル名が `_` で始まるモジュールは集約の対象外 (下書き用)
- `ALL_FORMATS` の順序は優先度ではない。優先度は利用者が `SymbolResolver` に渡す順で決まる
