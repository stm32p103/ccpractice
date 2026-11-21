# job-core

ジョブの受付・キュー管理のコア(ドメインとアプリケーション層)。用途・提出元・実行ツールに依存しない。
実行時の依存は **標準ライブラリのみ**。HTTP・DB は扱わず、外部との接点はすべてポートとして定義する。

設計の根拠: [spec](../specs/001-core-job-queue/spec.md) / [plan](../specs/001-core-job-queue/plan.md) /
[data-model](../specs/001-core-job-queue/data-model.md) / [脅威モデル](../docs/security/threat-model.md)

## 責務

- ジョブの提出(末尾、または指定した待機中のジョブの前後)と受付の判定(要件を満たしうるランナーの有無、重複)
- 1 本の待機列の並び順の管理(スケジュール変更)と、空いたランナーへの割り当て
- 取り消し・強制中断・やり直し、ジョブの状態遷移
- 状態を変える操作の監査ログ、ジョブ完了イベント(アウトボックス)、保持期間による削除
- 権限(permission)単位の可否の判定。認証はしない(呼び出し元が認証済みの主体を渡す)

## 公開 API

`job_core.job.application` から公開する名前だけを使う。入出力・拒否・権限の表は
[contracts/application-api.md](../specs/001-core-job-queue/contracts/application-api.md) を参照。

## ポートと実装の担当

| ポート | 約束 | 実装 |
|---|---|---|
| `UnitOfWork`、`JobRepository`、`QueueRepository`、`AuditLog`、`Outbox` | [contracts/ports.md](../specs/001-core-job-queue/contracts/ports.md) | Fake: `job_testing.core_fakes`。実アダプタ: core-persistence(003 と合わせて実装) |
| `RunnerEligibility` | 同上 | Fake: `job_testing.core_fakes`。実装: 002(ランナー管理) |
| `Clock`、`IdGenerator` | 同上 | Fake: `job_testing.core_fakes`。実装: 003 |

実アダプタは `job_testing.contracts` の契約テストを継承して実行し、Fake と同じテストを通すこと。
ジョブ完了イベントの形は [JSON Schema](src/job_core/job/schemas/job_completed.v1.json)(公開契約。版 1)。

## 作らないもの

- 優先度・自動の並べ替え(憲章 原則 5)
- 外部への送信(ネットワーク・外部プロセス)。依存規則と禁止 API は自動で検査する
- 定期実行の仕組み(保持期間による削除の定期実行は 003 / 009)
- 実行中の詳細な下位状態(リース、タイムアウト)。004 で追加する

## 検証

```powershell
.\ops\dev\setup-dev.ps1           # 構築(冪等)
.\ops\dev\setup-dev.ps1 -VerifyOnly  # quickstart.md の V1〜V11
```
