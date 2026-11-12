# バックログ(積み残し)

- 状態: `todo` / `doing` / `done` / `hold`
- 優先度: 高(今やる) / 中(次) / 低(必要になったら)
- 決定の経緯: `docs/decisions.md`

## 積み残し課題
| ID | 内容 | 関係 | 優先 | 状態 |
|---|---|---|---|---|
| BL-1 | 対応案: 利用者が AI とチャットしながら、依頼をもとにチームがやると決めたことをまとめる | UC-14 | 中 | todo |
| BL-2 | 対応状況: 対応案の項目ごとの状況をまとめる。対応案とファイルを分けるかを決める | UC-15 | 中 | todo |
| BL-3 | 監査エージェント: 対応案・対応状況の更新時に、依頼・対応案・対応状況の整合を確認する | UC-16 | 中 | todo |
| BL-4 | リスク: 監査で見つけた成立のリスク(不足、期限が近いのに未決事項が残る など)を要約する。解消したものは削除してよい | UC-16 | 中 | todo |
| BL-5 | 依頼どうしの関係の影響(期限の連動など)を知らせる | TM-D23、UC-12 | 低 | todo |
| BL-6 | 過去の知見の蓄積と検索 | TM-D09、UC-8、UC-9 | 中 | todo |
| BL-7 | 定例会のトピック、計画管理、課題対応管理 | UC-11〜UC-13 | 低 | todo |

## 機能の進捗
| 機能 | 段階 | 状態 | 備考 |
|---|---|---|---|
| 001-request-intake(依頼の受付) | 1 要件 | done(G1 承認 2026-11-13) | clarify 5 問済み |
| 001-request-intake | 2 設計(`/speckit-plan`) | todo | 次にやる |

## 引き継ぎメモ(2026-11-13)
- ブランチ: `001-request-intake`(`team-desk-concept` から派生)
  - `team-desk-concept` の PR が未作成なら作る: https://github.com/stm32p103/ccpractice/pull/new/team-desk-concept
- 次の作業: `/speckit-plan`
  - Copilot のフックの対応範囲を最新ドキュメントで確認する(TM-D14、concept Q4)
  - `tm.py` のサブコマンド構成、依頼ファイルの Pydantic モデル、`config/tm.yaml` の項目を決める
  - constitution(原則 I〜VI)への適合を確かめる
- 並行してできること(P4 評価)
  - 架空の依頼 3 件を gh の JSON 形式に変え、`eval-cases/request-intake/cases.yaml` を書く
  - 新しいセッションで、concept を読ませずに受付させ、スキル無しの基準を `eval-cases/request-intake/baseline/` に残す
- 環境: このPCに `gh` が未導入。P6(試験用の非公開リポジトリでの通し試験)の前に導入し `gh auth login`
