# Spec Kit 入力案(draft)

「ジョブの受付・キュー管理」「ランナーとジョブの管理」を、再利用できる汎用部品として作り、
最初の用途(評価機材に接続された Windows PC で動くチェックツールの実行)をその上に載せる。

## 実行順序

| 順 | ファイル | コマンド | 備考 |
|---|---|---|---|
| 0 | [00-build-vs-adopt.md](00-build-vs-adopt.md) | (Spec Kit 外) | 作る理由と、作らないものの線引き |
| 1 | [01-constitution.md](01-constitution.md) | `/speckit.constitution` | 再利用性の原則を含む |
| 2 | [02-modules.md](02-modules.md) | (参照用) | モジュール分割・依存規則。各 spec/plan から参照 |
| 3 | 03〜10 の specify 入力 | `/speckit.specify` | feature ごとに 1 つずつ |
| 4 | [11-clarify.md](11-clarify.md) | `/speckit.clarify` | 各 specify 後 |
| 5 | [12-plan.md](12-plan.md) | `/speckit.plan` | spec 承認後 |
| - | [13-security-egress.md](13-security-egress.md) | (参照用) | 機密保護: 書き出し台帳と対策。憲章・各 spec・plan から参照 |

## feature 一覧(実装順の目安)

| # | feature | ファイル | 今回の詳しさ |
|---|---|---|---|
| 001 | core-job-queue(ジョブの受付・管理) | [03-specify-001-core-job-queue.md](03-specify-001-core-job-queue.md) | 詳細 |
| 002 | runner-management(ランナーとジョブの管理) | [04-specify-002-runner-management.md](04-specify-002-runner-management.md) | 境界と最小のみ(別途詰める) |
| 003 | core-api(コア機能の API) | [05-specify-003-core-api.md](05-specify-003-core-api.md) | 詳細 |
| 004 | runner-agent(ランナーと外部ツールの実行) | [06-specify-004-runner-agent.md](06-specify-004-runner-agent.md) | 詳細(状態の詳細は別途) |
| 005 | github-integration(認証・認可・提出) | [07-specify-005-github-integration.md](07-specify-005-github-integration.md) | 詳細 |
| 006 | webui | [08-specify-006-webui.md](08-specify-006-webui.md) | 詳細 |
| 007 | notification | [09-specify-007-notification.md](09-specify-007-notification.md) | 簡易 |
| 008 | fault-tolerance | [10-specify-008-fault-tolerance.md](10-specify-008-fault-tolerance.md) | 簡易(数値は未確定) |
| 009 | environment-setup(環境構築・マイグレーション支援) | [14-specify-009-environment-setup.md](14-specify-009-environment-setup.md) | 詳細。基盤を最初の試行前に完成し、以後 feature ごとに拡張 |

001 → 003 → 004(002 の最小版を含む)→ 005 → 006 → 007 → 008 の順で(009 は 004 と並行して着手し、試行の前に完成)、
**GitHub 連携(005)がなくても、001〜004 だけで動作・テストできる**ことを区切りの条件にする。

## 前提(確定済み)

- サーバーとランナーはイントラネット内。ランナーはサーバーへアウトバウンド接続のみ。
- 1 ランナー 1 ジョブ。
- 利用者は提出の成否を提出元(GitHub Actions)で確認し、以後は WebUI で確認する。
- 実行環境は Windows PC のみ(仮想化不可)。
- 既存の Jenkins は選択肢から外れている(理由は [00-build-vs-adopt.md](00-build-vs-adopt.md))。CI は GitHub Actions に統一する。

## 重要要件: 機密漏洩への配慮

ワーカーと GitHub Actions のランナーは、ジョブ用の作業フォルダ**外**の情報(ファイル、環境変数、他のサービスの情報)を、
外部に送信せず、Git にコミットしない。外部へ書き出す情報は、出力先と内容を明示し、台帳にないものは禁止する。
憲章の「最重要原則 S1〜S6」、[13-security-egress.md](13-security-egress.md)、004/005 の機密保護の要件に反映した。

## 技術スタック(追加)

- WebUI は TypeScript + React + Fluent UI(v9)。Modern Web Guidance のスキルに従う(憲章の原則 13、006、plan)。
- 環境構築・運用スクリプトは Windows PowerShell(憲章の原則 14、009、plan)。インストーラは公式サイトから取得。秘密情報は Windows の資格情報の保管機能。

## 試行の進め方

- 試行は、各 feature の仕様が固まり、実装した後に、feature ごとに行う。
- 各 feature の「完了の定義」: (a) 試行できる状態、(b) その feature に必要な構築・マイグレーションが 009 のスクリプトで再現できる、(c) スモークテストに確認項目を追加。
- 最初の試行(001 + 003 を、偽のランナーで)の前に、009 の基盤(サーバー構築、DB 導入、マイグレーションの枠組み、共通部品)を完成させる。
- 以後は、004(ランナー構築のスクリプトを追加)→ 005 → 006 → 007 → 008(2 台構成のスクリプトを追加)の順に拡張する。

## 前回案からの主な変更

- 単一アプリ前提をやめ、**独立して使えるモジュールの集合**として再設計([02-modules.md](02-modules.md))。
- 用語を一般化: Task→**ジョブ**、機材/ワーカー→**ランナー**、機材要件→**ランナー要件(能力の条件)**。
  「評価機材」は最初の用途(プロファイル)の語彙であり、コアには持ち込まない。
- 依頼ファイルの解釈はコアの外(用途ごとの「プロファイル」)に出した。コアはファイルを読まない。
- Jenkins の不満点(入れ替え不可、突発対応・やり直し不可)を、コアの要件に明示した(001)。
- WebUI と GitHub 連携を、コア API だけに依存する利用者として分離した。
