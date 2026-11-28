# 技術的な構成

`/speckit-plan` の技術コンテキストとして使います。

## 技術コンテキスト

| 項目 | 内容 |
|---|---|
| 言語 | Python 3.12 以上 (型パラメータ構文 `class X[T]`、`type` 文を使う) |
| 依存 | `pyelftools` (ELF/DWARF の読み込み) のみ |
| 配布 | `pyproject.toml` (setuptools、`src/` 構成)。配布名 `dwarf-symbol-resolver`、パッケージ名 `dwarf_symbol_resolver` |
| 対象 | リトルエンディアン、DWARF 2〜5 を出せる処理系。検証済みは arm-none-eabi-gcc 15.3.1 |
| 開発ツール | `dsr-verify-toolchain`、`dsr-dwarf-survey`、`dsr-comment-catalog`、`dsr-comment-check` (pyproject の scripts) |

## 処理の流れ

```
利用者のツール
  左辺値 (マクロ可) ──[ビルドと同じプリプロセッサ -E]──> 展開済みの式
                                                          │
SymbolResolver.resolve(式)                                 ▼
  1. parse_lvalue: 式 → AccessPath (ルート変数, スコープ, メンバ/インデックスの並び)
     enum 定数は DebugInfoSource.enum_value で評価
  2. DebugInfoSource.find_variables: ルート変数 → Variable (model)。スコープで 1 つに絞る
  3. model の型をたどる: オフセット加算、配列の範囲確認、ビットフィールドのビット位置
  4. アドレス: Variable.address (デバッグ情報) を優先、SymbolAddressSource で補完・照合
  5. コメント: 宣言の位置 (SourceLoc) のソース行 → 候補 → CommentParser[T] を優先度順に
  6. Resolved[T] を返す
```

## モジュール構成

```
src/dwarf_symbol_resolver/
  __init__.py      公開 API の集約 (利用者はここだけ import する)
  model.py         処理系に依存しない型・変数のモデル
  lvalue.py        AccessPath と parse_lvalue (左辺値の文法)
  result.py        Resolved[T]
  resolver.py      SymbolResolver[T] (処理系に依存しない)
  errors.py        ResolveError
  sources/         処理系ごとの情報源
    base.py          DebugInfoSource / SymbolAddressSource (Protocol)
    dwarf/common.py  DwarfSource: 標準 DWARF の解釈 + フック
    dwarf/arm_gcc.py ArmGccDwarfSource (検証済み。フックの上書きなし)
    elf_symtab.py    ElfSymtabSource (ELF シンボル表)
  comments/        コメント解析
    base.py          CommentParser[T, P], RegexCommentParser[T, P], Sample, KeyValue, parse_first
    fields.py        dataclass 形式の parsed (MonitorFields)
    formats/         形式ごとのパーサ (1 形式 1 モジュール)。__init__.py は自動生成
    catalog.py       形式の集約・自己テスト・衝突確認・CATALOG.md の生成
    extract.py       ソースからのコメント候補の取り出し
    numbers.py       eval_fraction / try_fraction (四則演算だけの安全な数値評価)
    CATALOG.md       形式の一覧 (自動生成)
  examples/        利用例 (monitor_info.py、export_monitor_csv.py)
  devtools/        開発ツール (verify_toolchain、survey、comment_catalog、comment_check)
verification/      検証用のサンプルと処理系の設定、検証結果
.claude/skills/    dwarf-adapter / comment-parser / comment-parser-catalog
```

## データモデル (`model.py`) の正規化の約束

`DebugInfoSource` の実装は、処理系の表現を次の意味に揃えて返す。`SymbolResolver` はこの約束だけを前提にする。

- オフセット・サイズはバイト単位
- `Member.bit_pos` は「構造体の先頭からのビット位置」。ビット k はメモリ上の (k // 8) バイト目の (k % 8) ビット目 (LSB = 0)
- `Member.offset` はビットフィールドでは `bit_pos // 8` (参考値)
- `ArrayType.dims` は多次元配列の全次元 (外側から)。要素数が不明なら `None`
- 型の `name` は表示用 (typedef 名を優先し、修飾子を含む)。`volatile` は別のフラグでも持つ
- `Variable.unit` は翻訳単位のファイル名 (ディレクトリなし)。`func` は関数内 static の関数名
- `Variable.address` はデバッグ情報から得たアドレス。得られなければ `None`

型: `BaseType`、`EnumType`、`PointerType`、`StructType` (共用体を含む)、`ArrayType`。
列挙型: `Encoding` (SIGNED / UNSIGNED / FLOAT / BOOL)、`Linkage` (EXTERNAL / INTERNAL / LOCAL_STATIC)。

## 拡張点

| 拡張したいもの | 方法 | 変更してよい範囲 |
|---|---|---|
| 新しい処理系の DWARF | `DwarfSource` を継承し、フックを上書き (04 参照) | `sources/dwarf/<処理系>.py` を追加、公開一覧 (`__init__.py` 3 か所) に追加 |
| DWARF 以外のデバッグ情報 | `DebugInfoSource` Protocol を実装 | `sources/` にモジュールを追加 |
| アドレスの別の情報源 | `SymbolAddressSource` Protocol を実装 (`name`、`address_of`) | `sources/` にモジュールを追加 |
| 新しいコメント形式 | `RegexCommentParser` を継承 (04 参照) | `comments/formats/<形式>.py` を追加、必要なら `fields.py` に dataclass を追加 |
| コメントから作る情報 | 利用者が形式のクラスを継承して `build` を実装 | 利用者のコード (ライブラリは変更しない) |

`DwarfSource` のフック (処理系の癖を吸収する場所):

| フック | 標準の解釈 |
|---|---|
| `variable_address(die)` | `DW_AT_location` が `DW_OP_addr` 1 命令ならそのアドレス。それ以外 (`DW_OP_addrx`、ロケーションリスト) は `None` |
| `is_static_storage(die)` | 関数内の変数が固定アドレス (`DW_OP_addr`/`DW_OP_addrx`) を持つか |
| `linkage_of(die, func)` | 関数内なら LOCAL_STATIC、`DW_AT_external` なら EXTERNAL、それ以外は INTERNAL |
| `member_offset(die)` | `DW_AT_data_member_location` の定数、または `DW_OP_plus_uconst` のブロック (DWARF 2) |
| `bitfield_pos(die, unit_size)` | `DW_AT_data_bit_offset` (DWARF 4+) をそのまま。`DW_AT_bit_offset` (DWARF 2/3) は `メンバ位置*8 + 格納単位ビット数 - bit_offset - bit_size` に変換。ビッグエンディアンはエラー |
| `base_encoding(die)` | `DW_AT_encoding` (DW_ATE) → `Encoding` |
| `enum_encoding(die)` | 元の整数型があればその符号、なければ列挙子の値に負があれば SIGNED |
| `decl(die)` | `DW_AT_decl_file`/`DW_AT_decl_line`。ファイル番号は DWARF 5 で 0 始まり、4 以前は 1 始まり |
| `type_display_name(die)` | typedef 名を優先し、前に付いた修飾子を含める |

## 公開 API (互換性を保つ対象)

`dwarf_symbol_resolver.__all__` に含まれるもの。主なもの:

- `SymbolResolver(debug_info, address_sources=(), src_dirs=(), comment_parsers=())`、`.from_elf(elf_path, *, debug_info_cls=None, src_dirs=(), comment_parsers=())`、`.resolve(lhs)`、`.parse(text)`、`.close()`
- `Resolved[T]` のフィールド: `path, address, size, mask, shift, bit_size, ctype, encoding, root_address, root_offset, linkage, comment, comment_src, variable, notes`
- `Encoding`、`Linkage`、`ResolveError`、`AccessPath`、`parse_lvalue`
- `DebugInfoSource`、`SymbolAddressSource`、`DwarfSource`、`ArmGccDwarfSource`、`ElfSymtabSource`
- `CommentParser`、`RegexCommentParser`、`Sample`、`KeyValue`、`MonitorFields`、`parse_first`、`eval_fraction`、`try_fraction`
- 形式: `BracketCommentParser`、`KeyValueCommentParser`、`ALL_FORMATS`
