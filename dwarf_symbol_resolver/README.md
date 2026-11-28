# DWARF Symbol Resolver

C の左辺値 (変数、配列要素、構造体・共用体のメンバ、ビットフィールド) を、ビルド結果の ELF/DWARF から
**アドレス・読み出し幅・マスク・値の解釈 (符号付き/なし/浮動小数点)** に解決するライブラリです。
宣言のコメントから単位・LSB・オフセットなどを読み取ることもできます。RAM モニタツールの設定作りを想定しています。

## インストール

```
pip install -e .
```

Python 3.12 以上、依存は `pyelftools` のみです。

## 使い方

マクロは展開しません。マクロを含む左辺値は、ビルドと同じオプションでコンパイラのプリプロセッサ (`-E`) を通し、
展開後の式を渡してください (`##` による名前の組み立ても、これで扱えます)。

```python
from dataclasses import dataclass
from dwarf_symbol_resolver import (SymbolResolver, ArmGccDwarfSource, ElfSymtabSource,
                                   BracketCommentParser, MonitorFields, Encoding)

@dataclass
class MyInfo:                      # コメントから作る情報の型 (T) は利用者が決める
    unit: str | None
    lsb: str | None

class MyBracket(BracketCommentParser[MyInfo]):
    def build(self, parsed: MonitorFields) -> MyInfo:
        return MyInfo(parsed.unit, parsed.lsb)

resolver = SymbolResolver(ArmGccDwarfSource("app.elf"),
                          address_sources=[ElfSymtabSource("app.elf")],
                          src_dirs=["src"],                   # コメントを読むソースの場所
                          comment_parsers=[MyBracket()])      # 先頭ほど優先

r = resolver.resolve("st.ar[1].bits.level")      # 関数内 static は "func::var", ファイル内 static は "file.c::var"
print(hex(r.address), r.size, r.mask, r.shift, r.encoding, r.comment)
match r.encoding:
    case Encoding.FLOAT: ...
```

詳しい利用例は `src/dwarf_symbol_resolver/examples/` にあります
(`monitor_info.py`: T と build の実装例、`export_monitor_csv.py`: 左辺値の一覧から CSV を作るツールの見本)。

## 構成

| パス | 内容 |
|---|---|
| `src/dwarf_symbol_resolver/` | ライブラリ本体 (構成はパッケージの `__init__.py` の説明を参照) |
| `src/dwarf_symbol_resolver/sources/dwarf/` | 処理系ごとの DWARF 解析 (`common.py` が標準の解釈、`arm_gcc.py` など) |
| `src/dwarf_symbol_resolver/comments/formats/` | コメント形式ごとのパーサ (一覧は `comments/CATALOG.md`) |
| `src/dwarf_symbol_resolver/devtools/` | 開発用ツール (下記) |
| `verification/` | 処理系の検証用のサンプル (`sample.c`, `lvalues.txt`) と処理系の設定 (`toolchains/*.json`) |
| `.claude/skills/` | 処理系・コメント形式を追加するための Claude Code のスキル |

## 開発用ツール

| コマンド | 内容 |
|---|---|
| `dsr-verify-toolchain verification/toolchains/arm_gcc.json` | `verification/sample.c` をビルドし、解決結果をコンパイラの正解と比べて `verification/results/<処理系>/<バリアント>/result.md` を出す |
| `dsr-dwarf-survey app.elf` | ELF/DWARF の特徴 (アドレスの表し方、ビットフィールドの属性など) を調べる |
| `dsr-comment-catalog [--write]` | コメント形式を集約し、自己テストと衝突確認をして一覧を再生成する |
| `dsr-comment-check --pattern ... --excerpt ...` | 新しいコメント形式の正規表現の候補を、抜粋と既存の形式に対して確認する |

## 保守・機能追加の資料

仕様・構成・適合方法・動作確認・利用例は [docs/speckit/](docs/speckit/README.md) にまとめています
(Spec Kit に渡す入力として整理したもの)。

## 処理系・コメント形式の追加 (Claude Code のスキル)

- `dwarf-adapter`: 新しい処理系の DWARF 解析クラスを作る (ビルドコマンドを尋ね、ビルドできることを確認してから生成・検証する)
- `comment-parser`: ソースの抜粋から新しいコメント形式のパーサを作る (既存の形式との衝突は許容しない)
- `comment-parser-catalog`: コメント形式の一覧を再生成し、衝突を確認する
