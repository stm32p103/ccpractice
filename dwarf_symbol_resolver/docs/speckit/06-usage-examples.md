# 利用者 (ツール開発者) から見た使い方

ツール開発者は、このライブラリを組み込んで「左辺値の一覧 → RAM モニタの設定」を作るツールを書きます。
ライブラリが受け持つのは左辺値の解決とコメントの抽出までで、**T (コメントから作る情報) の型、値の加工、マクロ展開、出力形式はツール側** で決めます。

## 1. 最小の例

```python
from dwarf_symbol_resolver import SymbolResolver, Encoding

resolver = SymbolResolver.from_elf("app.elf")          # 既定: ArmGccDwarfSource + ELF シンボル表
r = resolver.resolve("st.ar[1].bits.level")

print(hex(r.address), r.size)        # 0x90f4 4    … 0x90F4 から 4 バイト読む
print(hex(r.mask), r.shift)          # 0xfff0 4    … (値 & mask) >> shift が level
print(r.encoding, r.linkage)         # Encoding.UNSIGNED Linkage.EXTERNAL

match r.encoding:
    case Encoding.FLOAT:    ...      # size=4 なら単精度、8 なら倍精度
    case Encoding.SIGNED:   ...      # ビットフィールドなら bit_size ビットで符号拡張
    case Encoding.UNSIGNED: ...
    case Encoding.BOOL:     ...
    case None:              ...      # 構造体・配列・ポインタ全体
```

static 変数の指定: ファイル内 static は `"sample.c::s_count"`、関数内 static は `"tick::call_cnt"`。

## 2. コメントを自分の型で受け取る

T は自ツールで決めます。形式のクラス (`BracketCommentParser` など) を継承して `build` を実装します。

```python
from dataclasses import dataclass
from fractions import Fraction
from dwarf_symbol_resolver import (SymbolResolver, ArmGccDwarfSource, ElfSymtabSource,
                                   BracketCommentParser, KeyValueCommentParser,
                                   MonitorFields, KeyValue, try_fraction)

@dataclass(frozen=True)
class Scale:                               # このツールの T
    unit: str | None
    lsb: Fraction | None
    offset: Fraction | None

class BracketScale(BracketCommentParser[Scale]):        # /* [rpm] LSB=1/128 OFS=0 ... */
    def build(self, p: MonitorFields) -> Scale:
        return Scale(p.unit, try_fraction(p.lsb), try_fraction(p.offset))

class KeyValueScale(KeyValueCommentParser[Scale]):      # ///< unit: mV, lsb: 5, ofs: -2560
    def build(self, p: KeyValue) -> Scale:
        return Scale(p.get("unit"), try_fraction(p.get("lsb")), try_fraction(p.get("ofs")))

resolver = SymbolResolver(
    ArmGccDwarfSource("app.elf"),               # 処理系に合ったクラス
    address_sources=[ElfSymtabSource("app.elf")],
    src_dirs=["src"],                           # コメントを読むソースの場所
    comment_parsers=[BracketScale(), KeyValueScale()],   # 先頭ほど優先
)
r = resolver.resolve("g_speed")
r.comment          # Scale(unit='rpm', lsb=Fraction(1, 128000), offset=Fraction(0, 1))
                   #   (sample.c: volatile int g_speed; /* [rpm] LSB=1/(128*1000) OFS=0 エンジン回転数 */)
r.comment_src      # 'sample.c:47' (コメントを探した宣言の位置)
```

同じ parsed 型を返す形式が複数あるときは、`build` だけを書いた mixin を共有できます:

```python
class ScaleBuild:
    def build(self, p: MonitorFields) -> Scale: ...
class MyFormatScale(ScaleBuild, MyFormatCommentParser[Scale]): pass
```

## 3. マクロで書かれた左辺値

ライブラリはマクロを展開しません。**ビルドと同じプリプロセッサとオプション** で展開してから渡します。
`##` による名前の組み立て、別マクロで部分パスを深くするもの、関数形式のマクロも、これで普通の式になります。

```c
/* 対象の翻訳単位を include し, 目印の間に左辺値を並べたファイルを作る (probe.c) */
#include "path/to/foo.c"
__LV_BEGIN_0__ ST_AR1_LEVEL __LV_END__
__LV_BEGIN_1__ SIG(eng, spd) __LV_END__
```

```
arm-none-eabi-gcc -E -P <ビルドと同じ -D / -I> probe.c -o probe.i
```

`probe.i` の目印の間が展開後の式です (`(((st.ar[1]).bits).level)`、`(g_eng_spd)`)。
展開後に残る定数式や enum 定数はライブラリが評価します。
スコープ指定 (`tick::`) はマクロ展開の対象外なので、展開後の式の前に付け直してください。

## 4. 実行できるサンプル: 左辺値の一覧 → CSV

`src/dwarf_symbol_resolver/examples/export_monitor_csv.py` が、上の 1〜3 を組み合わせたツールの見本です。

```
python -m dwarf_symbol_resolver.examples.export_monitor_csv \
    --elf verification/results/arm_gcc/v4/app.elf \
    --context verification/sample.c --src-dir verification \
    --cpp "arm-none-eabi-gcc -E -P {src} -o {out}" \
    --lvalues verification/lvalues.txt -o monitor.csv
```

出力の例 (抜粋):

```
name,expr,address,bytes,mask,shift,bits,type,unit,lsb,offset,description
g_speed,g_speed,0x000090B0,4,,,32,signed,rpm,7.8125e-06,0.0,エンジン回転数
AR_AT(1),(g_ar[2 + (1) * 2]),0x000090BC,2,,,16,signed,degC,0.1,-40.0,温度
tick::call_cnt,call_cnt,0x0000916C,4,,,32,unsigned,count,1.0,0.0,関数内static
ST_AR1_LEVEL,(((st.ar[1]).bits).level),0x000090F4,4,0xFFF0,4,12,unsigned,%,0.0244140625,0.0,出力レベル
ST_AR1_WIDE,(((st.ar[1]).bits).wide),0x000090F8,2,0xFFC,2,10,unsigned,mV,5.0,-2560.0,電圧
```

構成:

| 関数 | 役割 | 担当 |
|---|---|---|
| `expand_macros` | プリプロセッサでマクロを展開 | ツール側 |
| `SymbolResolver.resolve` | 左辺値の解決とコメントの抽出 | ライブラリ |
| `MonitorInfo` / `MONITOR_PARSERS` (`examples/monitor_info.py`) | T と `build` | ツール側 |
| `to_row` | `Resolved` → CSV の 1 行 | ツール側 |

## 5. 再ビルド後の再計算

DWARF を毎回読み直すので、定数のチューニングや小さなロジック変更の後も、新しい ELF で `SymbolResolver` を作り直すだけで
正しいアドレスが得られます。構造体にメンバを足した、配列の長さが変わった、といった配置の変化にも追従します
(ソースの解析結果をキャッシュする方式ではないため)。マクロ展開の結果は、マクロの定義が変わらない限り使い回せます。
