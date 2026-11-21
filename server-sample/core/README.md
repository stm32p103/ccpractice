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

## runner コンテキスト(002 ランナーとジョブの割り当ての管理)

設計の根拠: [spec](../specs/002-runner-management/spec.md) / [plan](../specs/002-runner-management/plan.md) /
[data-model](../specs/002-runner-management/data-model.md)。同じ `job_core` の中のコンテキスト `job_core.runner` として加え、
依存は `runner → job` の一方向(`job` は `runner` を import しない。import-linter で検査する)。

- **責務**: ランナーの作成・起動時の登録(能力の自己申告。許可リストに載ったキーだけ)、状態(online / offline /
  異常 / maintenance。時刻と設定から導く)、異常と回復の申告、ランナーのトークン(発行・失効・認証)、
  要件と能力の照合(判定と割り当てで同じ純粋関数)、割り当てとリース(生存通知で延長)、定期処理
- **公開 API**: `job_core.runner.application` から公開する名前だけを使う。入出力・拒否・権限・監査は
  [contracts/application-api.md](../specs/002-runner-management/contracts/application-api.md)。
  要件と能力の申告の形は JSON Schema(版 1。[要件](src/job_core/runner/schemas/runner_requirement.v1.json)、
  [申告](src/job_core/runner/schemas/capability_declaration.v1.json))
- **権限**: `runner.manage`(人間・サービス)、`runner.report`(ランナーのトークンにだけ付く)、`runner.sweep`(定期処理)。
  ランナーのトークンで認証した主体は `{runner.report, job.execute}` だけを持つ

| ポート | 約束 | 実装 |
|---|---|---|
| `RunnerUnitOfWork`、`RunnerRepository`、`LeaseRepository`、`RunnerTokenRepository`、`CapabilityAllowlistRepository`、`RunnerCatalog` | [contracts/ports.md](../specs/002-runner-management/contracts/ports.md) | Fake: `job_testing.core_fakes`。実アダプタ: core-persistence(003 と合わせて実装) |
| `RunnerEligibility`(001 のポート) | 同上 | `RunnerEligibilityService`(002) |
| `SecretGenerator` | 同上 | `SystemSecretGenerator`(標準ライブラリ `secrets`)。Fake: `job_testing.core_fakes` |

引き継ぎ(plan.md「他の feature への引き継ぎ」): 003 はランナーからの要求ごとに `AuthenticateRunner` を呼び、
`SweepRunners` を 15 秒ごとに呼ぶ(認証の失敗の流量の制限も 003)。004 は起動時の `RegisterRunner`、
`heartbeat_interval` ごとの `Heartbeat`、PC 内のツールからの異常と回復の経路、リース切れのジョブの扱い。
009 はランナーの作成とトークンの PC への設定の手順。

## 作らないもの

- 優先度・自動の並べ替え(憲章 原則 5)
- 外部への送信(ネットワーク・外部プロセス)。依存規則と禁止 API は自動で検査する
- 定期実行の仕組み(保持期間による削除の定期実行は 003 / 009)
- 実行中の詳細な下位状態(タイムアウトなど)と、リース切れのジョブの扱い。004 で追加する
- ランナーの自動検出、能力の自動取得、機材の故障の自動検知(002 のスコープ外)

## 検証

```powershell
.\ops\dev\setup-dev.ps1           # 構築(冪等)
.\ops\dev\setup-dev.ps1 -VerifyOnly  # quickstart.md の V1〜V18(001 の V1〜V11、002 の V12〜V18)
```
