# 契約: アプリケーション層のユースケース(core の公開 API)

**対象**: `job_core.job.application`(Python の公開インターフェース)
**利用者**: core-api(003)、ランナー側の取得経路(003 / 004)、結合テスト
**版**: 0.1.0(core パッケージの版に従う。互換性を壊す変更はメジャーを上げる。憲章 原則 1)

HTTP の形(パス、状態コード)は 003 で定める。ここでは、ユースケースの**入力・出力・拒否**だけを定める。
各ユースケースは、呼び出し元が認証済みの `Principal` を渡す前提とする(FR-024)。

---

## 共通の約束

- 状態を変えるユースケースは、1 回の Unit of Work で「判定 → 変更 → 監査ログ → アウトボックス」をまとめて確定する。途中で拒否されたら何も変えない。
- 楽観的排他の衝突(`ConcurrencyConflict`)は、ユースケースの内部で最新の状態を読み直して**判定からやり直す**(既定 3 回)。
  やり直しを使い切った場合だけ、呼び出し元へ `ConcurrencyConflict` を返す(呼び出し元は再試行してよい)。
- 権限による拒否(`PermissionDenied`)と、割り当て先でないランナーからの報告(`RunnerMismatch`)は、監査ログに `DENIED` として記録する(FR-025)。他の拒否は記録しない。
- 拒否は `JobCoreError` の派生の例外で返す。各例外は機械可読の `code` を持つ(下表)。
- 判定の順序: ① 入力の形式 → ② 対象の存在 → ③ 権限(対象の**その時点の**状態と所有で判定)→ ④ ドメインの規則。
  ただし提出は、① 権限 → ② 定義の検証 → ③ ランナーの判定 → ④ 基準のジョブ → ⑤ 重複 の順。

## 権限

| 権限(`Permission`) | 値 | 許す操作 |
|---|---|---|
| `JOB_SUBMIT` | `job.submit` | 自分の名義の提出(末尾)、終了したジョブのやり直し(末尾) |
| `GENERAL` | `job.general` | 自分のジョブの取り消し・強制中断、全ジョブと操作の経緯の閲覧 |
| `QUEUE_SCHEDULE` | `queue.schedule` | 位置を指定した提出・やり直し、待機中のジョブの移動 |
| `CANCEL_QUEUED` | `job.cancel_queued` | 全ての待機中のジョブの取り消し |
| `FORCE_ABORT` | `job.force_abort` | 全ての実行中のジョブの強制中断 |
| `AUDIT_READ_ALL` | `audit.read_all` | 監査ログ全体の閲覧 |
| `SUBMIT_ON_BEHALF` | `job.submit_on_behalf` | 別の提出者の名義での提出 |
| `JOB_EXECUTE` | `job.execute` | ジョブの割り当ての取得、終了の報告、停止の確認(ランナー用。003 がランナーの主体に付与する) |
| `RETENTION_PURGE` | `retention.purge` | 保持期間による削除の実行(定期実行の主体用) |
| `RUNNER_MANAGE` | `runner.manage` | ランナーの作成・maintenance・異常の手動の解除・削除・トークン・許可リストの変更(002 で追加) |
| `RUNNER_REPORT` | `runner.report` | ランナーの登録・生存通知・異常と回復の申告(002 で追加。ランナーのトークンにだけ付く) |
| `RUNNER_SWEEP` | `runner.sweep` | ランナーの定期処理の実行(002 で追加。定期実行の主体用) |
| `ACCESS_MANAGE` | `access.manage` | サービス用の認証情報の発行・失効・一覧、アクセス設定(対応表)の参照・再読み込み、利用者のセッションの一括の失効(003 で追加。人間のロールに載せられる) |

`JOB_SUBMIT` 〜 `SUBMIT_ON_BEHALF` の 7 種は spec FR-023 の権限、`JOB_EXECUTE` と `RETENTION_PURGE` は plan で追加した権限(FR-023 の「少なくとも」の範囲。research.md R8)。
`RUNNER_*` の 3 種は 002 の権限(002 research.md R10)。`ACCESS_MANAGE` は 003 の権限(003 research.md R6)。権限は合計 13 種で、001 の可否の判定は変わらない(追加の権限は 001 のユースケースの可否に影響しない)。
可否は**権限だけ**で判定し、主体の種類(`Principal.kind`)は判定に使わない(憲章 原則 9)。

### 可否の表

「自分」= 対象のジョブの名義上の提出者(`submitter.owner`)が `principal.subject_id` と一致する。

| 操作 | 条件 | 必要な権限 |
|---|---|---|
| 提出(末尾) | 自分の名義 | `JOB_SUBMIT` |
| 提出(末尾) | 他人の名義(`on_behalf_of` あり) | `SUBMIT_ON_BEHALF` |
| 提出(位置指定) | — | 上記 + `QUEUE_SCHEDULE` |
| やり直し(末尾) | 誰のジョブでも | `JOB_SUBMIT` |
| やり直し(位置指定) | 誰のジョブでも | `JOB_SUBMIT` + `QUEUE_SCHEDULE` |
| 移動 | 誰のジョブでも | `QUEUE_SCHEDULE` |
| 中断 | 自分の待機中/実行中 | `GENERAL` |
| 中断 | 他人の待機中 | `CANCEL_QUEUED` |
| 中断 | 他人の実行中 | `FORCE_ABORT` |
| 一覧・詳細・操作の経緯 | 誰のジョブでも | `GENERAL` |
| 監査ログ全体 | — | `AUDIT_READ_ALL` |
| 割り当て・終了の報告・停止の確認 | — | `JOB_EXECUTE` |
| 保持期間による削除 | — | `RETENTION_PURGE` |

## 拒否の一覧

| 例外 | `code` | 意味 | 追加の情報 |
|---|---|---|---|
| `ValidationFailed` | `validation_failed` | ジョブ定義の必須項目がない、タイムアウトが正でない、文字数の超過(FR-003) | `field`、`detail` |
| `NoEligibleRunner` | `no_eligible_runner` | 要件を満たしうるランナーが登録されていない(FR-002) | — |
| `DuplicateQueuedJob` | `duplicate_queued_job` | 同じ内容のジョブが待機中(FR-006) | `existing_job_id` |
| `PermissionDenied` | `permission_denied` | 権限がない | `required`(権限の候補の一覧) |
| `JobNotFound` | `job_not_found` | 存在しない(削除済みを含む) | `job_id` |
| `TargetNotQueued` | `target_not_queued` | 移す・取り消すジョブが待機中でない(FR-012) | `job_id`、`state` |
| `AnchorNotQueued` | `anchor_not_queued` | 基準のジョブが待機中でない、または待機列が空(FR-004a、FR-012) | `anchor_job_id` |
| `SelfAnchor` | `self_anchor` | 自分自身を基準にした移動(FR-012) | — |
| `InvalidStateTransition` | `invalid_state_transition` | 規則にない遷移(FR-021)。終了済みの中断、待機中/実行中のやり直し(US4-3)など | `from_state`、`operation` |
| `ReasonRequired` | `reason_required` | 強制中断の理由がない(FR-016) | — |
| `AbortAlreadyRequested` | `abort_already_requested` | 中断の要求が既にある | `requested_at` |
| `RunnerBusy` | `runner_busy` | そのランナーに未終了のジョブがある(FR-010) | `job_id` |
| `RunnerMismatch` | `runner_mismatch` | 終了の報告・停止の確認をしたランナーが、そのジョブの割り当て先(`Job.assigned_runner_id`)でない。権限による拒否と同じく、監査ログに `DENIED` として記録する | `job_id` |
| `ConcurrencyConflict` | `concurrency_conflict` | 内部のやり直しを使い切った | — |

---

## コマンド(状態を変える)

### SubmitJob — 提出(US1、US2、FR-001〜007)

入力:

| 項目 | 型 | 必須 | 説明 |
|---|---|---|---|
| `principal` | `Principal` | ✔ | |
| `definition` | `JobDefinition` の各項目 | ✔ | [data-model.md](../data-model.md#jobdefinitionジョブ定義) |
| `on_behalf_of` | `SubjectId` | — | 提出代行の名義上の提出者 |
| `placement` | `Placement`(`anchor`、`side`) | — | 省略時は末尾 |

出力: `SubmitResult(job_id, position)`

拒否: `PermissionDenied`、`ValidationFailed`、`NoEligibleRunner`、`AnchorNotQueued`、`DuplicateQueuedJob`
監査: `SUBMIT` または `SUBMIT_PLACED`

### RescheduleJob — スケジュール変更(US2、FR-011〜013)

入力: `principal`、`job_id`、`placement`(必須)
出力: `RescheduleResult(job_id, position_before, position_after)`(位置が変わらない場合も成功。前後が同じ値)
拒否: `JobNotFound`、`PermissionDenied`、`SelfAnchor`、`TargetNotQueued`、`AnchorNotQueued`
監査: `RESCHEDULE`

### CancelJob — 取り消し・強制中断(US3、FR-014〜016)

入力: `principal`、`job_id`、`reason`(待機中は任意、実行中は必須)
出力: `CancelResult(job_id, state, abort_pending: bool)`
- 待機中 → 即時に `CANCELLED`(`abort_pending = false`)。
- 実行中 → 中断の要求を記録し、状態は `RUNNING` のまま(`abort_pending = true`)。確定は `ConfirmStopped`。
拒否: `JobNotFound`、`PermissionDenied`、`InvalidStateTransition`(終了済み)、`ReasonRequired`、`AbortAlreadyRequested`
監査: `CANCEL_QUEUED` または `ABORT_REQUEST`

権限は**その時点の状態**で判定する。同時に割り当てが成立して実行中になった場合、内部のやり直しで実行中として判定し直す(Edge Cases)。

### RetryJob — やり直し(US4、FR-017〜020)

入力: `principal`、`job_id`(元のジョブ)、`placement`(任意)
出力: `SubmitResult(job_id, position)`(新しいジョブ)
- 新しいジョブの定義 = 元のジョブの定義。提出者(`owner` と `submitted_by`)= やり直した主体。`retry_of` = 元のジョブ。
拒否: `JobNotFound`(削除済みを含む)、`PermissionDenied`、`InvalidStateTransition`(終了していない)、`NoEligibleRunner`、`AnchorNotQueued`、`DuplicateQueuedJob`
監査: `RETRY`(新しいジョブを対象とし、`retry_of` を記録)

### AssignNextJob — 割り当て(US1、FR-009〜010)

入力: `principal`(`JOB_EXECUTE`)、`runner_id`
出力: `AssignResult(job_id | None)`(該当なしは `None`)
拒否: `PermissionDenied`、`RunnerBusy`
監査: `ASSIGN`(割り当てたときだけ)

002 の変更: 本体を `assign_next_in(uow, deps, principal, runner_id, satisfies, *, lease_id=None)` として切り出した(`AssignNextJob` はそれを呼ぶだけで、振る舞いは変わらない)。
002 の `RequestJob` が、ランナーの状態の確認とリースの作成を同じ UoW で行うために再利用する。`ASSIGN` の記録には `runner_id`(と、あれば `lease_id`)が付く。

### ReportFinished — 終了の報告(004 から)

入力: `principal`(`JOB_EXECUTE`)、`runner_id`(報告するランナー)、`job_id`、`outcome`(`SUCCEEDED | FAILED`)、`result_summary`(任意)
出力: `FinishResult(job_id, state, superseded_abort: bool)`
拒否: `JobNotFound`、`PermissionDenied`、`RunnerMismatch`、`InvalidStateTransition`、`ValidationFailed`(要約が長すぎる)
判定の順序: 存在 → 権限 → 割り当て先の一致 → 状態。`runner_id` が呼び出し元のランナーの主体に対応することは、呼び出し元(003。ランナーごとのトークン)が保証する(FR-024 と同じ前提)。
監査: `COMPLETE`。アウトボックス: `JobCompleted`

### ConfirmStopped — 停止の確認(004 から)

入力: `principal`(`JOB_EXECUTE`)、`runner_id`(停止を確認したランナー)、`job_id`
出力: `FinishResult(job_id, state=CANCELLED, superseded_abort=false)`
拒否: `JobNotFound`、`PermissionDenied`、`RunnerMismatch`、`InvalidStateTransition`(要求がない、または終了済み)
判定の順序と `runner_id` の前提は ReportFinished と同じ。
監査: `ABORT_CONFIRM`。アウトボックス: `JobCompleted`

### PurgeExpired — 保持期間による削除(FR-031、FR-032)

入力: `principal`(`RETENTION_PURGE`)、`policy: RetentionPolicy`
出力: `PurgeResult(jobs_deleted, audit_records_deleted)`
拒否: `PermissionDenied`
監査: `PURGE`(1 回の実行につき 1 件)

---

## 問い合わせ(状態を変えない)

すべて `GENERAL` を要する(監査ログ全体を除く)。

### ListJobs — 一覧(US5、FR-022)

入力: `principal`、`states`(任意の絞り込み)、`cursor` / `limit`(終了済みの一覧の頁送り。既定 100)
出力: `JobListView`
- `queued`: 待機中の全件を**待機列の並び順**で(`position` を含む)
- `running`: 実行中の全件
- `finished`: 終了済みを `finished_at` の新しい順で頁送り
各行 `JobSummaryView`: `job_id`、`job_type`、`owner`、`submitted_by`、`state`、`position`、`submitted_at`、`started_at`、`finished_at`、`result_summary`、`abort_pending`、`retry_of`。
payload は含めない(詳細で取得)。

### GetJob — 詳細(US5)

入力: `principal`、`job_id`
出力: `JobDetailView` = `JobSummaryView` + `definition`(payload を含む。ログ本文・成果物は 004)、`cancellation`、
`retry_of: RelatedJobRef(job_id, exists: bool)`(元のジョブが削除済みなら `exists = false`)、`retries: list[JobId]`(このジョブを元にしたやり直し)
拒否: `JobNotFound`、`PermissionDenied`

### GetJobHistory — 操作の経緯(US6、FR-026)

入力: `principal`、`job_id`
出力: `list[AuditRecordView]`(対象のジョブの `SUCCEEDED` の記録を時刻順)。`DENIED` は含めない(US6-4)。
削除済みのジョブでも、監査ログが残っていれば返す(FR-032 の目的)。

### GetAuditLog — 監査ログ全体(US6、FR-026)

入力: `principal`(`AUDIT_READ_ALL`)、`since` / `until`、`job_id` / `actor` / `operation` / `outcome` / `runner_id`(任意。`runner_id` は 002 で追加)、`cursor` / `limit`
出力: `list[AuditRecordView]`(`DENIED` を含む)
拒否: `PermissionDenied`(この拒否も記録する)

---

## 受け入れシナリオとの対応(抜粋)

| シナリオ | ユースケース | 期待 |
|---|---|---|
| US1-1 | SubmitJob | `NoEligibleRunner`、待機列は不変 |
| US1-5 | AssignNextJob | 先頭が条件を満たさなくても、満たす最前のジョブ |
| US1-6 | SubmitJob | `DuplicateQueuedJob(existing_job_id)` |
| US2-1 | SubmitJob(`placement=BEFORE A`) | X、A、B、C。実行中のジョブは不変 |
| US2-6 | SubmitJob / RescheduleJob | `PermissionDenied`、待機列は不変、拒否を記録 |
| US3-5 | CancelJob | `CANCEL_QUEUED` だけの主体が他人の実行中を中断 → `PermissionDenied` |
| US4-6 | RetryJob(`placement`) | B の直前。権限がなければ `PermissionDenied` でジョブは作られない |
| US6-4 | GetJobHistory | `DENIED` は含まれない |
