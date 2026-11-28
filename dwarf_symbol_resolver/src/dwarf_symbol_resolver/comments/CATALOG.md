# コメント形式カタログ

`dsr-comment-catalog --write` (devtools/comment_catalog.py) で自動生成。手で編集しない。

| 形式 (クラス) | モジュール | parsed | サンプル数 | 状態 |
|---|---|---|---|---|
| `BracketCommentParser` | `formats/bracket.py` | `MonitorFields` | 4 | OK |
| `KeyValueCommentParser` | `formats/key_value.py` | `KeyValue` | 2 | OK |

## 衝突

- なし

## BracketCommentParser

`/* [単位] LSB=式 OFS=式 説明 */` または `// [単位] ...`。LSB= / OFS= / 説明は省略可。

判定の特徴: コメント記号の直後 (空白可) が `[`。

- モジュール: `formats/bracket.py`
- parsed: `MonitorFields`

判定・抽出の正規表現 (fullmatch, 前後の空白は除去):

```regex
(?:/\*|//)\s*\[(?P<unit>[^\]]*)\]\s*(?:LSB=(?P<lsb>\S+))?\s*(?:OFS=(?P<offset>\S+))?\s*(?P<description>.*?)\s*(?:\*/)?
```

| サンプル | 期待する parsed | 出典 |
|---|---|---|
| `/* [rpm] LSB=1/(128*1000) OFS=0 エンジン回転数 */` | `MonitorFields(unit='rpm', lsb='1/(128*1000)', offset='0', description='エンジン回転数')` | sample.c |
| `/* [degC] LSB=0.1 OFS=-40 温度 */` | `MonitorFields(unit='degC', lsb='0.1', offset='-40', description='温度')` | sample.c |
| `/* [-] 有効フラグ */` | `MonitorFields(unit='-', lsb=None, offset=None, description='有効フラグ')` | sample.c |
| `// [V] LSB=2 電源電圧` | `MonitorFields(unit='V', lsb='2', offset=None, description='電源電圧')` | - |

## KeyValueCommentParser

`///< unit: 単位, lsb: 式, ofs: 式, desc: 説明`。キーは小文字に正規化する。

判定の特徴: `///<` で始まり, `キー: 値` を 1 つ以上含む。
parsed のキー: unit, lsb, ofs, desc (書かれているものだけ)

- モジュール: `formats/key_value.py`
- parsed: `KeyValue`

判定・抽出の正規表現 (fullmatch, 前後の空白は除去):

```regex
///<\s*(?P<body>\w+\s*:.*)
```

| サンプル | 期待する parsed | 出典 |
|---|---|---|
| `///< unit: mV, lsb: 5, ofs: -2560, desc: 電圧` | `{'unit': 'mV', 'lsb': '5', 'ofs': '-2560', 'desc': '電圧'}` | sample.c |
| `///< unit: -, lsb: 1, ofs: 0, desc: 2次元テーブル` | `{'unit': '-', 'lsb': '1', 'ofs': '0', 'desc': '2次元テーブル'}` | sample.c |
