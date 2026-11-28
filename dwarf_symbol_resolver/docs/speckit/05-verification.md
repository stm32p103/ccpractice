# 動作確認の方法

すべての変更で、次の 2 つが通ることを完了条件にします (01 の完了条件)。

## 準備

```
pip install -e .
```

処理系の検証には、その処理系 (検証済みのものは `arm-none-eabi-gcc`) が PATH にあること。

## 1. 処理系の検証 `dsr-verify-toolchain`

```
dsr-verify-toolchain verification/toolchains/arm_gcc.json            # 全バリアント
dsr-verify-toolchain verification/toolchains/arm_gcc.json v4         # バリアントを指定
dsr-verify-toolchain verification/toolchains/arm_gcc.json --build-only
dsr-verify-toolchain verification/toolchains/arm_gcc.json v4 --debug-info dwarf_symbol_resolver.sources.dwarf.common:DwarfSource
```

### 何をしているか

1. `verification/sample.c` をプリプロセス・コンパイル・リンクする (設定のコマンドで)
2. `verification/lvalues.txt` の左辺値を、処理系のプリプロセッサで展開する
   (`probe.c` = `#include "sample.c"` + 目印付きの左辺値 → `probe.i`)
3. `app.elf` を、設定の `DebugInfoSource` と `ElfSymtabSource` で解決する
4. **正解をコンパイラに出させる**: `verify.c` (`#include "sample.c"` するので static も参照できる) を同じオプションでビルドし、
   - 通常: `&(lhs)` と `sizeof(lhs)` の値
   - ビットフィールド: ルート変数と同じ型のゼロ初期化オブジェクトで、対象のフィールドだけを `-1` (全ビット 1) にした初期化イメージ
   を `verify.elf` から読み、`verify.elf` を同じ方法で解決した結果と比べる
5. 関数内 static は関数の外から `&` で参照できないため、ELF シンボル表のアドレス (GCC なら `name.N`) との一致だけを確認する (△)
6. 結果を `verification/results/<処理系>/<バリアント>/result.md` に書く。
   内容: 実行したコマンド、まとめ、考察 (設定の `remarks`)、`dsr-dwarf-survey` の観察、左辺値ごとの表

### 合格の判定

- 正常系: すべて `✓` (関数内 static は `△`)
- `!` で始まる左辺値 (エラー期待): すべてエラー
- 終了コード 0

### 現在の基準となる結果

arm-none-eabi-gcc 15.3.1、`-mcpu=cortex-m4 -O0 -g3`、DWARF 2/3/4/5 のすべてで:

| | 件数 |
|---|---|
| 正常系 29 件: コンパイラの正解と一致 | 28 |
| 正常系 29 件: シンボル表との照合のみ (関数内 static) | 1 |
| エラー期待 3 件: 正しくエラー | 3 |

### 検証用のサンプル

`verification/sample.c` は次を含む。検証項目を足すときは `sample.c` と `lvalues.txt` の両方に足し、全処理系で再検証する。

- 単純な変数 (外部結合、ファイル内 static、関数内 static)
- 1 次元・2 次元の配列、enum をインデックスに使う配列
- 構造体のネスト、構造体の配列、ビットフィールド (`:0` による格納単位の切り替えを含む)、共用体
- マクロ: 単純、部分パスを別マクロで深くするもの、関数形式、`##` 連結 (変数名・enum 名)、定数式のインデックス
- コメント: 2 形式 (`[単位] LSB= OFS=` と `///< unit:, lsb:, ofs:, desc:`)

`lvalues.txt` の書式: 1 行 1 件、`#` はコメント、`scope::expr` でスコープ指定、`!expr` はエラー期待。

## 2. コメント形式の検査 `dsr-comment-catalog`

```
dsr-comment-catalog            # 検査だけ
dsr-comment-catalog --write    # 検査 + formats/__init__.py と CATALOG.md の再生成
```

合格の判定: 全形式 `OK` (自分のサンプルすべてに合致し、期待値どおりに抽出できる)、衝突 0 件、終了コード 0。
現在: 2 形式とも OK、衝突 0 件。

## 3. DWARF の調査 `dsr-dwarf-survey` (判定ではなく調査用)

```
dsr-dwarf-survey verification/results/arm_gcc/v4/app.elf
```

ELF の基本情報、CU ごとの DWARF のバージョンと producer、変数の `DW_AT_location` の形式、ビットフィールドの属性の組み合わせ、
タグごとの属性と FORM、標準外の属性、static 変数の候補 (シンボル表のローカルシンボル) を出す。
pyelftools で読めない箇所があれば、そのエラーも出す。

## 4. 利用例の動作確認

```
python -m dwarf_symbol_resolver.examples.export_monitor_csv \
    --elf verification/results/arm_gcc/v4/app.elf \
    --context verification/sample.c --src-dir verification \
    --cpp "arm-none-eabi-gcc -E -P {src} -o {out}" \
    --lvalues verification/lvalues.txt -o monitor.csv
```

29 行の CSV が出て、終了コード 0 になること (`!` の行は読み飛ばす)。

## 自動テストについて

現在、pytest などの単体テストはありません。動作確認は上の検証ツールだけです (07 の候補を参照)。
