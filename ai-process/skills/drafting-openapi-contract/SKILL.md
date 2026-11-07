---
name: drafting-openapi-contract
description: 要件書（REQ-xxx の要件ID付き）から OpenAPI 3.0 の API 契約を起こす、または既存の契約を要件の変更に合わせて更新する。requirements.md から openapi.yaml を作るとき、要件追加に合わせて契約を直すとき、API 設計のレビュー前に使う。
---
# 要件から API 契約を起こす

## 入出力の約束事
- 入力: 要件書（要件ID付き）。更新の場合は現行の契約も
- 出力:
  - 契約: OpenAPI 3.0（YAML）。各 operation に `x-req-ids`（その operation が担う要件IDの配列）を付ける
  - 未決事項: 要件から判断できなかった点を、要件IDと「何が決まっていないか」「決めるのに誰の判断が要るか」の形で書く
  - 返答: `{status, outputs, key_points, unresolved, process_version, model}` のJSON
- 人は YAML ではなく、契約から機械的に作った表（操作・要件ID・応答）で確認する。だから `summary` と応答の `description` は、その表だけで意味が分かるように短く書く

## 手順
1. 要件を1件ずつ読み、「誰が・何を・どの条件で・失敗したらどうなるか」に分ける
2. （ベースライン後に追記）
3. 書き終えたら、すべての要件IDがどこかの `x-req-ids` にあるかを確かめる

## 判断の方針
- 要件に書かれていない値や規則は決めない。未決事項に書く
- （ベースライン後に追記: スキル無しの実行でつまずいた点をここに書く）

## よくある失敗
- （評価の結果から追記）
