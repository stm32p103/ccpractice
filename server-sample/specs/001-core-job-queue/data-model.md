# データモデル: コア — ジョブの受付・キュー管理

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **調査**: [research.md](research.md)

core のドメインモデル(Python の値オブジェクト・集約)を定める。DB のテーブル設計ではない。
永続化の表現は core-persistence が決め、[contracts/ports.md](contracts/ports.md) の契約テストを通すこと。

コンテキスト(憲章 原則 2):

- **job**: ジョブ、待機列、監査ログの記録、ジョブ完了イベント
- **access**: 主体(Principal)と権限(Permission)。値オブジェクトだけを公開する
- **runner**(002): 001 では識別子 `RunnerId` で参照するだけ

---

## 1. 値オブジェクト

| 名前 | 型・形 | 検証 | 出典 |
|---|---|---|---|
| `JobId` | 不透明な文字列 | 空でない | FR-004 |
| `RunnerId` | 不透明な文字列(002 が発行) | 空でない | Key Entities |
| `SubjectId` | 不透明な文字列(認証済みの主体の識別子) | 空でない | FR-024 |
| `JobType` | 文字列 | 前後の空白を除き 1〜128 文字 | FR-001、FR-003 |
| `RunnerRequirement` | 不透明な値(002 が形を定める。001 は等価比較と保持のみ) | 必須 | R5 |
| `Payload` | JSON で表せる値を深くコピーした不変の値 | 必須。中身は検査しない | FR-001 |
| `Timeout` | `timedelta` | 正の値 | FR-003 |
| `SourceRef` | `source: str`(1〜512)、`revision: str \| None`(1〜256) | 形式は検査しない | FR-006、R12 |
| `ResultSummary` | 文字列 | 1024 文字以内。超えたら拒否 | R12 |
| `Reason` | 文字列 | 前後の空白を除き 1〜1000 文字 | FR-016 |
| `Placement` | `anchor: JobId`、`side: BEFORE \| AFTER` | 自分自身を基準にできない(移動時) | FR-004a、FR-011 |
| `DuplicateKey` | `(source, revision, job_type)` | `SourceRef` があるときだけ存在 | FR-006、R11 |

### JobDefinition(ジョブ定義)

| 項目 | 型 | 必須 |
|---|---|---|
| `job_type` | `JobType` | ✔ |
| `requirement` | `RunnerRequirement` | ✔ |
| `payload` | `Payload` | ✔ |
| `timeout` | `Timeout` | ✔ |
| `source_ref` | `SourceRef \| None` | — |

- やり直し(FR-018)では、元のジョブの `JobDefinition` を**そのまま**新しいジョブに渡す(同一の値)。
- `duplicate_key()` は `source_ref` があれば `DuplicateKey` を、なければ `None` を返す。

### Submitter(提出者)

| 項目 | 型 | 説明 |
|---|---|---|
| `owner` | `SubjectId` | 名義上の提出者。「自分のジョブ」の判定に使う |
| `submitted_by` | `SubjectId` | 実際に提出した主体。通常は `owner` と同じ。提出代行ではサービスの主体 |

### Principal(access コンテキスト)

| 項目 | 型 | 説明 |
|---|---|---|
| `subject_id` | `SubjectId` | 認証済みの主体(呼び出し元が検証済み。FR-024) |
| `permissions` | `frozenset[Permission]` | [contracts/application-api.md の権限表](contracts/application-api.md#権限) |
| `kind` | `HUMAN \| SERVICE \| SYSTEM \| RUNNER \| ANONYMOUS` | 監査ログの表示用。可否の判定には使わない(判定は権限だけで行う)。`ANONYMOUS` は 003 で追加(認証に失敗した呼び出しの `actor_kind`。権限を持たない) |

`kind` は監査ログの `AuditRecord.actor_kind` に写すためだけに使う。ランナーの操作(割り当て・終了の報告・停止の確認)や保持期間による削除の可否も、
`kind` ではなく `Principal.permissions`(`job.execute`、`retention.purge`)で判定する(憲章 原則 9。contracts/application-api.md「権限」)。

---

## 2. 集約: Job(ジョブ)

| 項目 | 型 | 説明 |
|---|---|---|
| `job_id` | `JobId` | 一意 |
| `definition` | `JobDefinition` | 不変 |
| `submitter` | `Submitter` | 不変 |
| `submitted_at` | `datetime`(UTC) | 不変 |
| `state` | `JobState` | 下記の遷移表に従う |
| `assigned_runner_id` | `RunnerId \| None` | `RUNNING` 以降で設定 |
| `started_at` | `datetime \| None` | 割り当ての日時 |
| `finished_at` | `datetime \| None` | 終了の確定日時。保持期間の起点(FR-031) |
| `result_summary` | `ResultSummary \| None` | 終了の報告で設定 |
| `cancellation` | `CancellationRecord \| None` | 中断の記録 |
| `retry_of` | `JobId \| None` | やり直しの元のジョブ(FR-018)。元のジョブが削除されても値は残す |
| `version` | `int` | 楽観的排他(R4) |

- 「元のジョブからやり直しのジョブを辿る」(US4-1)は、`retry_of = 元のジョブ` の問い合わせで得る。元のジョブの集約は変更しない(FR-018)。
- 状態の変更は集約のメソッドだけで行い、規則にない遷移は `InvalidStateTransition` を送出する(FR-021、憲章 原則 2)。
- ジョブ完了イベント `JobCompleted` は、終了状態への遷移のメソッドの中で集約に積まれる(FR-027)。

### CancellationRecord(中断の記録)

| 項目 | 型 | 説明 |
|---|---|---|
| `kind` | `QUEUED_CANCEL \| FORCE_ABORT` | 待機中の取り消し / 実行中の強制中断 |
| `requested_by` | `SubjectId` | |
| `requested_at` | `datetime` | |
| `reason` | `Reason \| None` | `FORCE_ABORT` では必須(FR-016) |
| `confirmed_at` | `datetime \| None` | 中断の確定日時。`QUEUED_CANCEL` では `requested_at` と同じ |
| `superseded_by` | `SUCCEEDED \| FAILED \| None` | 停止の確認より先に終了が確定した場合に設定(Edge Cases) |

### JobState と遷移表

状態: `QUEUED`(待機中)、`RUNNING`(実行中)、`SUCCEEDED`(成功)、`FAILED`(失敗)、`CANCELLED`(中断)。
終了状態 = `SUCCEEDED / FAILED / CANCELLED`。

| メソッド | 遷移前 | 遷移後 | 前提 | 副作用 |
|---|---|---|---|---|
| `assign(runner_id, at)` | `QUEUED` | `RUNNING` | — | `assigned_runner_id`、`started_at` |
| `cancel_queued(by, reason?, at)` | `QUEUED` | `CANCELLED` | — | `cancellation(kind=QUEUED_CANCEL, confirmed_at=at)`、`finished_at`、`JobCompleted` |
| `request_abort(by, reason, at)` | `RUNNING`(中断の要求なし) | `RUNNING` | `reason` 必須 | `cancellation(kind=FORCE_ABORT, confirmed_at=None)` |
| `request_abort(...)` | `RUNNING`(要求済み) | — | — | `AbortAlreadyRequested` で拒否(先の要求を保つ) |
| `confirm_stopped(runner_id, at)` | `RUNNING`(要求済み) | `CANCELLED` | `runner_id = assigned_runner_id` | `confirmed_at`、`finished_at`、`JobCompleted` |
| `confirm_stopped(runner_id, at)` | `RUNNING`(要求なし) | — | — | `InvalidStateTransition` |
| `finish(runner_id, outcome, summary?, at)` | `RUNNING` | `SUCCEEDED` / `FAILED` | `runner_id = assigned_runner_id` | `result_summary`、`finished_at`、`JobCompleted`。要求済みなら `cancellation.superseded_by = outcome` |
| 上記すべて | 終了状態 | — | — | `InvalidStateTransition`(FR-021) |
| `assign` / `cancel_queued` | `RUNNING` | — | — | `InvalidStateTransition` |
| `request_abort` / `finish` | `QUEUED` | — | — | `InvalidStateTransition` |
| `finish` / `confirm_stopped` | `RUNNING` | — | `runner_id ≠ assigned_runner_id` | `RunnerMismatch`(状態は変わらない。状態の検査より先に行う) |

```text
            assign                finish(SUCCEEDED|FAILED)
  QUEUED ─────────────▶ RUNNING ───────────────────────▶ SUCCEEDED / FAILED
    │                     │  ▲
    │ cancel_queued       │  │ request_abort(中断の要求を記録。状態は変わらない)
    ▼                     └──┘
  CANCELLED ◀──────────────── confirm_stopped(要求済みのときだけ)
```

`RUNNING` の内側の下位状態(開始の確認、リース切れ、タイムアウト)は 004 で追加する(R7)。

---

## 3. 集約: Queue(待機列)

| 項目 | 型 | 説明 |
|---|---|---|
| `queue_id` | 固定値 `"default"` | 待機列は 1 本(FR-008) |
| `entries` | `list[JobId]`(順序付き) | 待機中のジョブの並び。先頭が次の割り当ての候補 |
| `version` | `int` | 楽観的排他(R4) |

### 不変条件

1. `entries` に同じ `JobId` は 2 度現れない。
2. `entries` のジョブはすべて `QUEUED`、かつ `QUEUED` のジョブはすべて `entries` にある
   (2 つの集約にまたがるため、同じ UoW の中でアプリケーション層が両方を更新して守る。契約テストで検査する)。
3. 移動・追加・取り出しで、対象以外のジョブの相対的な順序は変わらない(FR-011)。

### 操作

| メソッド | 効果 | 拒否の条件 |
|---|---|---|
| `append(job_id)` | 末尾に追加(FR-004) | 既にある |
| `insert(job_id, placement)` | 基準のジョブの直前/直後に追加(FR-004a) | 基準が `entries` にない → `AnchorNotQueued`(末尾に切り替えない) |
| `move(job_id, placement)` | 対象を外し、基準の直前/直後に入れる(FR-011) | 対象がない → `TargetNotQueued`、基準がない → `AnchorNotQueued`、対象 = 基準 → `SelfAnchor`(FR-012) |
| `remove(job_id)` | 取り出し(割り当て・取り消し) | ない → `TargetNotQueued` |
| `position_of(job_id) -> int \| None` | 1 始まりの位置 | — |
| `first_matching(pred) -> JobId \| None` | 先頭から走査して最初に `pred` を満たすもの(FR-009) | — |

- 位置が変わらない移動(既に B の直前にある A を「B の前」へ)は成功とし、`entries` を変えない。監査ログには変更前後が同じ位置として記録する(Edge Cases)。
- 待機列が空のときの位置指定は、基準が存在しないため `AnchorNotQueued`(Edge Cases)。

### 永続化の推奨(core-persistence 向け)

各待機中のジョブに文字列の順位キー(fractional indexing)を持たせ、移動では対象の 1 行だけを更新する。
`version` は待機列ごとに 1 行の管理表で持ち、更新のたびに増やす。ドメインには `list[JobId]` として復元する。

---

## 4. 監査ログの記録: AuditRecord

追記専用。変更・個別の削除はしない(保持期間による削除のみ。FR-032)。

| 項目 | 型 | 説明 |
|---|---|---|
| `record_id` | 文字列 | 一意 |
| `occurred_at` | `datetime`(UTC) | 保持期間の起点 |
| `actor` | `SubjectId` | 操作者(提出代行では実際に提出した主体) |
| `actor_kind` | `HUMAN \| SERVICE \| SYSTEM \| RUNNER \| ANONYMOUS` | |
| `on_behalf_of` | `SubjectId \| None` | 提出代行の名義上の提出者(FR-024) |
| `operation` | `AuditOperation` | 下表 |
| `job_id` | `JobId \| None` | 対象(削除の集計では `None`) |
| `before` | `Mapping[str, JSON値]` | 変更前の値 |
| `after` | `Mapping[str, JSON値]` | 変更後の値 |
| `reason` | `Reason \| None` | 中断の理由など |
| `outcome` | `SUCCEEDED \| DENIED` | |
| `runner_id` | `RunnerId \| None` | 対象のランナー(002 で追加。既定 `None`。001 の操作では `ASSIGN` だけが付ける) |
| `denial` | `{ code, required } \| None` | 拒否の内容。`code` は `permission_denied` または `runner_mismatch`(002 で `authentication_failed`、`invalid_declaration` を追加)。`required` は必要な権限の候補の一覧(`PermissionDenied.required` と同じ。`runner_mismatch` では空) |

`before` / `after` に payload を入れない(監査ログは閲覧されるため、payload は不要な複製を作らない)。

| `AuditOperation` | `before` | `after` |
|---|---|---|
| `SUBMIT` | — | `state`、`position`、`retry_of` |
| `SUBMIT_PLACED` | — | `state`、`position`、`anchor`、`side` |
| `RETRY` | — | `state`、`position`、`retry_of`、(位置指定時)`anchor`、`side` |
| `RESCHEDULE` | `position` | `position`、`anchor`、`side` |
| `CANCEL_QUEUED` | `state`、`position` | `state` |
| `ABORT_REQUEST` | `state` | `state`、`abort_requested: true` |
| `ABORT_CONFIRM` | `state` | `state` |
| `ASSIGN` | `state`、`position` | `state`、`runner_id`、(002 の `RequestJob` のとき)`lease_id` |
| `COMPLETE` | `state` | `state`、`superseded_abort`(該当時) |
| `PURGE` | — | `jobs_deleted`、`audit_records_deleted`、`cutoffs` |
| `READ_AUDIT_LOG` | — | —(監査ログ全体の閲覧。状態を変えないため、権限による拒否のときだけ `DENIED` として記録する) |

003 が `AuditOperation` に加える値(`LOGIN`、`LOGOUT`、`AUTH_FAILED`、`SERVICE_CREDENTIAL_ISSUE`、`SERVICE_CREDENTIAL_REVOKE`、`ACCESS_CONFIG_CHANGE`)は、
[003 research.md R10](../003-core-api/research.md) を参照する(`job_id` を持たない。認証情報の値・ハッシュは記録しない)。

002 が `AuditOperation` に加える値(ランナー管理の 17 種。`RUNNER_CREATE`、`RUNNER_REGISTER`、`RUNNER_ONLINE` など)と、その `before` / `after` は
[002 data-model.md §7](../002-runner-management/data-model.md) を参照する。

- 拒否の記録(権限による拒否と、割り当て先でないランナーからの終了の報告・停止の確認)は `outcome = DENIED`、`before` / `after` は空、`after` に試みた操作の要点(位置指定の有無など)を入れてよい。
- **操作の経緯**(FR-026)= `job_id` が一致し、`outcome = SUCCEEDED` の記録を `occurred_at` 順に並べたもの。
- **監査ログ全体**= すべての記録(`DENIED` を含む)。`audit.read_all` を要する。

---

## 5. ドメインイベント: JobCompleted

契約: [contracts/job-completed-event.schema.json](contracts/job-completed-event.schema.json)

| 項目 | 型 | 説明 |
|---|---|---|
| `event_id` | 文字列 | 一意。受け手は重複除去に使う |
| `event_type` | `"job.completed"` | |
| `schema_version` | `1` | |
| `occurred_at` | `datetime` | イベントの発生日時 |
| `job_id` | `JobId` | |
| `state` | `SUCCEEDED \| FAILED \| CANCELLED` | |
| `finished_at` | `datetime` | |
| `retry_of` | `JobId \| None` | やり直しの関連 |
| `submitter_id` | `SubjectId` | 名義上の提出者 |

payload・ログ本文・結果の要約・ランナーの情報を持たない(FR-030、spec「外部への書き出し」、台帳 E10 / E9)。

### OutboxEntry(アウトボックス)

| 項目 | 型 | 説明 |
|---|---|---|
| `event` | `JobCompleted` | |
| `status` | `PENDING \| DISPATCHED` | |
| `recorded_at` | `datetime` | 終了の確定と同じ UoW で記録(FR-027) |
| `dispatched_at` | `datetime \| None` | |
| `attempts` | `int` | 配信側(003 / 007)が更新 |

---

## 6. 設定値: RetentionPolicy

| 項目 | 型 | 既定 | 検証 |
|---|---|---|---|
| `job_retention` | `timedelta` | 365 日 | 正の値 |
| `audit_retention` | `timedelta` | 1095 日 | 正の値、かつ `>= job_retention`(FR-032) |

---

## 7. 要件との対応

| 要件 | モデル上の担保 |
|---|---|
| FR-001〜003 | `JobDefinition` の検証、`RunnerEligibility.any_registered_runner_may_satisfy` |
| FR-004、004a、005 | `Queue.append` / `Queue.insert`。優先度の項目を持たない |
| FR-006 | `DuplicateKey` と待機中のジョブの照合 |
| FR-008〜012 | `Queue` の不変条件と操作 |
| FR-013 | 追加・移動の操作は `RUNNING` のジョブに触れない(`Queue` は待機中だけを持つ) |
| FR-014〜016 | `cancel_queued` / `request_abort` / `confirm_stopped`、`CancellationRecord` |
| FR-017〜020 | `retry_of`、定義の引き継ぎ、`Submitter.owner = やり直した主体` |
| FR-021 | 遷移表 |
| FR-025〜027 | `AuditRecord`、`JobCompleted`、`OutboxEntry` |
| FR-030 | `JobCompleted` の項目の固定 |
| FR-031〜032 | `RetentionPolicy`、`finished_at` / `occurred_at` を起点とする削除 |
