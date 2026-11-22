# 契約: HTTP API(版 1)

**対象**: `job_core_api`(core-api)が公開する HTTP API
**利用者**: WebUI(006)、GitHub 連携(005)、他のクライアント、ランナーエージェント(004)
**版**: `/v1`(R3)。正式な定義は、実装から生成する OpenAPI(`core-api/openapi/openapi-v1.json`)。本書は設計時の契約で、生成物と一致させる(契約テスト)。

すべての操作は、コアのユースケース([001](../../001-core-job-queue/contracts/application-api.md)、[002](../../002-runner-management/contracts/application-api.md))の入力・出力・拒否に、HTTP の形を与えるだけで、ドメインの規則を持たない。

---

## 1. 共通の約束

### 1.1 認証情報

| 方法 | 対象 | 備考 |
|---|---|---|
| `Authorization: Bearer <値>` | すべての主体 | 値の先頭 `ss_`(セッション)、`st_`(サービス)、`rt_`(ランナー)で種類を判別する(R4) |
| Cookie `__Host-session`(設定で `session`) | 人間の利用者(ブラウザ) | `HttpOnly`、`SameSite=Strict`。状態を変える呼び出しは `Origin` を検査する(R5) |

認証が要らない操作: `GET /v1/auth/login`、`GET /v1/auth/callback`、`POST /v1/auth/login`、`GET /healthz`。それ以外は認証が要る。
認証の失敗(未知・失効・期限切れ・形式の誤り)は区別せず `401`(`authentication_failed`)。

### 1.2 形式

- 要求・応答の本文は `application/json`(UTF-8)。エラーは `application/problem+json`(§3)。日時は RFC 3339 の UTC(`2026-11-21T09:00:00Z`)。
- 識別子(ジョブ、ランナーなど)は不透明な文字列。クライアントは形を仮定しない。
- **未知の項目・列挙値を無視する**(クライアントの規約。互換を保つ追加のため。R3)。
- すべての応答に `X-Request-Id` を付ける。要求に同名のヘッダがあれば(1〜64 文字の英数字と `-_`)、その値を使う。
- 一覧の頁送りは、不透明な `cursor`(応答の `next_cursor` を、次の要求の `cursor` に渡す。`null` なら最後)と `limit`。

### 1.3 権限

「必要な権限」の列は、コアのユースケースが判定する権限(001 の可否の表、002)。API は主体を渡すだけで、不足はコアが `permission_denied` として返し、`DENIED` を監査ログに記録する。
**API の層で判定する**操作は、「API」と記す(拒否は同じ `permission_denied`、同じく監査ログに記録)。

---

## 2. エンドポイント

生成クライアントが扱いやすいよう、本文を取る操作の本文は必須とする(項目がすべて任意なら `{}`)。

### 2.1 認証・セッション(API)

| メソッド・パス | 説明 | 認証 | 成功 | 主な拒否 |
|---|---|---|---|---|
| `GET /v1/auth/login?return_to=` | 認証基盤へ送る(`begin_login`)。`return_to` は同一オリジンの相対パス | 不要 | `302` | `404`(遷移の要らない方式)、`400 request_invalid`(`return_to` の不正)、`503 identity_provider_unavailable` |
| `GET /v1/auth/callback?...` | 認証基盤からの戻り。全クエリを `complete_login` に渡し、セッションを作り、Cookie を設定して `return_to` へ | 不要 | `302` | `401 authentication_failed`、`503 identity_provider_unavailable` |
| `POST /v1/auth/login` | 本文 `{"proof": {"<名前>": "<値>"}, "delivery": "cookie"\|"token"}` から、セッションを作る(Fake、非ブラウザのクライアント用) | 不要 | `200` `SessionInfo`。`delivery = token` のときだけ `session_token` を含む | `401`、`503` |
| `GET /v1/auth/session` | 呼び出した主体の情報 | 要 | `200` `SessionInfo` | `401` |
| `DELETE /v1/auth/session` | ログアウト(セッションの失効) | セッション | `204` | `401` |

`SessionInfo`: `principal_kind`、`subject_id`、`display_name`、`permissions`(現在の対応表で導いた権限の一覧)、`expires_at`、`idle_expires_at`、(`session_token`)。
`permissions` は、画面が操作の表示を切り替えるための情報で、最終の認可は API が判定する(006 FR-9)。サービス・ランナーの主体でも `GET /v1/auth/session` は使える(期限は `null`)。

### 2.2 ジョブ(001)

| メソッド・パス | 説明 | 必要な権限 | ユースケース | 成功 |
|---|---|---|---|---|
| `POST /v1/jobs` | 提出。本文: `definition`(`job_type`(必須)、`requirement`、`payload`、`timeout_seconds`、`source`、`revision`)、`on_behalf_of`(任意)、`placement`(任意: `anchor_job_id`、`side` = `before`\|`after`) | `job.submit`。代理は `job.submit_on_behalf`。位置指定は `queue.schedule` も | `SubmitJob` | `201` `SubmitResult`、`Location: /v1/jobs/{id}` |
| `GET /v1/jobs` | 履歴の検索。クエリ: `state`(複数)、`submitter`、`submitted_from`、`submitted_to`、`cursor`、`limit`。payload を含まない | `job.general` | `SearchJobs`(R8) | `200` `JobPage` |
| `GET /v1/jobs/{job_id}` | 詳細(`definition` を含む。ログ本文・成果物は 004) | `job.general` | `GetJob` | `200` `JobDetail` |
| `GET /v1/jobs/{job_id}/history` | 操作の経緯(成功した操作) | `job.general` | `GetJobHistory` | `200` `AuditRecord` の配列 |
| `POST /v1/jobs/{job_id}/reschedule` | スケジュール変更。本文: `placement`(必須) | `queue.schedule` | `RescheduleJob` | `200` `RescheduleResult` |
| `POST /v1/jobs/{job_id}/cancel` | 取り消し・強制中断。本文(必須。`{}` でよい): `reason`(待機中は任意、実行中は必須) | 自分: `job.general`、他人の待機中: `job.cancel_queued`、他人の実行中: `job.force_abort` | `CancelJob` | `200` `CancelResult` |
| `POST /v1/jobs/{job_id}/retry` | やり直し。本文(必須。`{}` でよい): `placement`(任意) | `job.submit`(位置指定は `queue.schedule` も) | `RetryJob` | `201` `SubmitResult` |
| `GET /v1/queue` | 待機列(待機中の全件を、待機列の順序で。`position` つき。payload を含まない) | `job.general` | `ListJobs`(待機中) | `200` `Queue` |

`on_behalf_of` を指定できるのは、`job.submit_on_behalf` を持つ主体だけ(サービス用の認証情報など)。指定がなければ、提出者は呼び出した主体になる。
`cancel` は、待機中なら即時に中断の状態になり(`abort_pending = false`)、実行中なら中断を要求する(`abort_pending = true`)。確定はランナーの停止の確認(§2.6)。

### 2.3 ランナーの管理(002)

| メソッド・パス | 説明 | 必要な権限 | ユースケース | 成功 |
|---|---|---|---|---|
| `POST /v1/runners` | 作成。本文: `name`。トークンの値はこの応答だけ | `runner.manage` | `CreateRunner` | `201` `CreatedRunner` |
| `GET /v1/runners` | 一覧(名前の順。トークンの情報を含まない) | `job.general` | `ListRunners` | `200` |
| `GET /v1/runners/{runner_id}` | 詳細 | `job.general` | `GetRunner` | `200` `RunnerView` |
| `GET /v1/runners/{runner_id}/history` | 操作の経緯 | `job.general` | `GetRunnerHistory` | `200` |
| `PUT /v1/runners/{runner_id}/maintenance` | maintenance にする。本文(必須。`{}` でよい): `reason`(任意) | `runner.manage` | `SetMaintenance` | `200` `RunnerView` |
| `DELETE /v1/runners/{runner_id}/maintenance` | maintenance を解除する | `runner.manage` | `ClearMaintenance` | `200` `RunnerView` |
| `DELETE /v1/runners/{runner_id}/fault` | 機材の異常を手動で解除する | `runner.manage` | `ClearFault` | `200` `RunnerView` |
| `DELETE /v1/runners/{runner_id}` | 削除(未終了のジョブがあれば拒否) | `runner.manage` | `DeleteRunner` | `204` |
| `POST /v1/runners/{runner_id}/token` | トークンの再発行(旧は失効)。値はこの応答だけ | `runner.manage` | `ReissueToken` | `200` `IssuedToken` |
| `DELETE /v1/runners/{runner_id}/token` | トークンの失効 | `runner.manage` | `RevokeToken` | `204` |
| `GET /v1/capability-allowlist` | 能力のキーの許可リスト | `job.general` | `GetCapabilityAllowlist` | `200` |
| `PUT /v1/capability-allowlist` | 許可リストの置き換え。本文: `entries`、`reason`(任意) | `runner.manage` | `ReplaceCapabilityAllowlist` | `200` |

### 2.4 監査ログ(001)

| メソッド・パス | 説明 | 必要な権限 | ユースケース | 成功 |
|---|---|---|---|---|
| `GET /v1/audit-log` | 監査ログ全体(拒否を含む)。クエリ: `since`、`until`、`job_id`、`actor`、`operation`、`outcome`、`runner_id`、`cursor`、`limit` | `audit.read_all` | `GetAuditLog` | `200` |

### 2.5 アクセスの管理(API)

| メソッド・パス | 説明 | 必要な権限 | 成功 | 主な拒否 |
|---|---|---|---|---|
| `POST /v1/service-credentials` | サービス用の認証情報の発行。本文: `name`、`permissions`(上限の部分集合)。値はこの応答だけ | `access.manage` | `201` `IssuedServiceCredential` | `422 validation_failed`(上限外の権限、名前)、`409 duplicate_credential_name` |
| `GET /v1/service-credentials` | 一覧(値・ハッシュを含まない) | `access.manage` | `200` | — |
| `DELETE /v1/service-credentials/{credential_id}` | 失効(即時) | `access.manage` | `204` | `404 credential_not_found` |
| `DELETE /v1/access/sessions?subject_id=` | 指定した利用者のセッションをすべて失効 | `access.manage` | `204` | — |
| `GET /v1/access/mapping` | 現在の対応表(ロール → 権限、所属グループ → ロール、上限、`digest`) | `access.manage` | `200` | — |
| `POST /v1/access/reload` | 設定ファイルの再読み込み(検証してから差し替え) | `access.manage` | `200`(`digest` の前後、差分の要約) | `400 access_config_invalid`(理由の一覧。現在の対応表は変わらない) |

### 2.6 ランナー向け(最小。R16。004 が拡張する)

ランナーの識別子は URL に含めない。認証した主体(`rt_` のトークン)のランナーだけが対象になる(FR-011)。権限は `runner.report`(要求と報告は `job.execute` も)で、`AuthenticateRunner` が付ける。

| メソッド・パス | 説明 | ユースケース | 成功 |
|---|---|---|---|
| `POST /v1/runner/registration` | 起動時の登録。本文: `capabilities`([002 の申告のスキーマ](../../002-runner-management/contracts/capability-declaration.schema.json)) | `RegisterRunner` | `200` `HeartbeatResult` |
| `POST /v1/runner/heartbeat` | 生存通知(リースの延長) | `Heartbeat` | `200` `HeartbeatResult` |
| `POST /v1/runner/fault` | 機材の異常の申告。本文: `description`(1〜200 文字) | `ReportFault` | `200` `HeartbeatResult` |
| `DELETE /v1/runner/fault` | 機材の異常からの回復の申告 | `ReportRecovered` | `200` `HeartbeatResult` |
| `POST /v1/runner/job-requests` | 割り当ての要求 | `RequestJob` | `200` `JobRequestResult`(割り当てなしも `200`) |
| `POST /v1/runner/jobs/{job_id}/result` | 終了の報告。本文: `outcome`(`succeeded`\|`failed`)、`result_summary`(任意) | `ReportFinished` | `200` `FinishResult` |
| `POST /v1/runner/jobs/{job_id}/stopped` | 停止の確認 | `ConfirmStopped` | `200` `FinishResult` |

`JobRequestResult` の割り当て(`Assignment`)は、ジョブ定義(payload を含む)を持つ。この応答だけが、payload をランナーへ返す(台帳 E16)。
ランナー以外の主体(人間・サービス)は、このエンドポイントを呼べない(`runner.report` を持たないため `permission_denied`)。

### 2.7 イベントの購読

`GET /v1/events` — `text/event-stream`。権限: `job.general`(API)。

- クエリ: `topics`(任意。`job`、`runner`、`queue` の部分集合。既定はすべて)。ヘッダ: `Last-Event-ID`(再接続)。
- 各イベント: `id: <epoch>:<seq>`、`event: <type>`、`data: <ChangeEvent の JSON>`([change-event.schema.json](change-event.schema.json))。
- 接続の直後に `event: hello`(`data: {"epoch": "...", "heartbeat_seconds": 15}`)を送る。以後、15 秒ごとに `: keepalive` のコメント行。
- `Last-Event-ID` の続きが範囲内なら、取りこぼした分を順に送る。範囲外・世代違いなら `event: resync` を送る(クライアントは `GET /v1/queue`、`GET /v1/jobs`、`GET /v1/runners` を再取得し、以後の通知を受ける)。
- 認証情報の失効・期限切れ、権限の喪失は、15 秒以内に検知して `event: auth.expired` を送り、接続を閉じる。
- 接続の上限(既定 200)を超えたら `503 sse_capacity_exceeded`。

### 2.8 運用

| メソッド・パス | 説明 | 認証 | 成功 |
|---|---|---|---|
| `GET /healthz` | 生存の確認(プロセスが応答できるか。依存を見ない) | 不要 | `200` `{"status": "ok"}`。接続元の許可リスト(R11)は適用する |
| `GET /openapi.json` | この版の OpenAPI(実装から生成) | 要 | `200` |

---

## 3. エラー

形式: [problem.schema.json](problem.schema.json)。`code` はコアの例外の `code`([001](../../001-core-job-queue/contracts/application-api.md#拒否の一覧)、[002](../../002-runner-management/contracts/application-api.md))をそのまま使い、API が加える `code` を下に示す。
**写像の表にない例外は `500 internal_error`**(詳細なし。R7)。

### 3.1 状態コードの対応

| 状態コード | `code` | 追加の項目 |
|---|---|---|
| `400` | `request_invalid`(形式の誤り)、`access_config_invalid`、`return_to_invalid` | `errors`(`location`、`reason` の配列。値は含めない) |
| `401` | `authentication_failed` | — |
| `403` | `permission_denied`、`runner_mismatch`(認証した主体が対象を操作できない。002 の `RunnerIdentityMismatch` を含む) | `required_permissions`(権限の候補。`permission_denied` のみ) |
| `403` | `network_not_allowed`(接続元の許可リスト。本文は固定) | — |
| `403` | `origin_not_allowed`(Cookie での状態変更の `Origin` の不一致) | — |
| `404` | `job_not_found`、`runner_not_found`、`credential_not_found`、`not_found`(遷移の要らない認証方式の `GET /v1/auth/login` など) | `job_id`、`runner_id`、`credential_id` |
| `409` | `duplicate_queued_job`、`target_not_queued`、`anchor_not_queued`、`invalid_state_transition`、`abort_already_requested`、`runner_busy`、`runner_has_unfinished_job`、`duplicate_runner_name`、`duplicate_credential_name`、`already_in_maintenance`、`not_in_maintenance`、`runner_deleted`、`lease_expired`、`invalid_lease_transition`、`concurrency_conflict` | `existing_job_id`、`anchor_job_id`、`job_id`、`from_state`、`operation`、`requested_at` |
| `405` | `method_not_allowed` | — |
| `413` | `payload_too_large` | — |
| `422` | `validation_failed`、`no_eligible_runner`、`self_anchor`、`reason_required`、`invalid_declaration`、`invalid_requirement`、`runner_not_registered` | `field`、`reason`(`validation_failed`。`reason` はコアの固定の規則の文面で、入力値を含まない。`detail` は全 `code` で固定の文面)、`violations`(`invalid_declaration`。キーと理由だけ) |
| `500` | `internal_error` | — |
| `503` | `identity_provider_unavailable`、`sse_capacity_exceeded` | — |

- `concurrency_conflict` は、コアが再試行を使い切った場合だけ。クライアントは再試行してよい(`Retry-After: 1`)。
- `no_eligible_runner` は `422`: 要求自体は正しいが、現在の登録済みのランナーでは満たせない(ランナーの登録後に、同じ要求が受け付けられうる)。
- 認証の失敗の `401` には、`WWW-Authenticate: Bearer` を付ける。

### 3.2 開示の規則(FR-014)

- エラーの本文に含めない: 認証情報、payload、ログの本文、異常の説明、能力の値、他の主体の情報(識別子を除く)、内部の例外の文字列・スタック。
- `permission_denied` は、必要な権限の候補だけを示す。`invalid_declaration` は、違反したキーと理由の種類だけを示す(002 T-R4)。
- 認証の失敗は、原因(未知・失効・期限切れ)を示さない。

---

## 4. 受け入れシナリオとの対応(抜粋)

| 受け入れ | 操作 | 期待 |
|---|---|---|
| US1-1〜4(spec) | `POST /v1/jobs`、`reschedule`、`cancel`、`retry` | 生成クライアントだけで成立 |
| US2-1(spec) | サービスの `st_` で `POST /v1/jobs`(`on_behalf_of`) | `201`。`GET /v1/audit-log` で名義上の提出者と代理元の両方 |
| US2-2(spec) | 人間の利用者が `on_behalf_of` を指定 | `403 permission_denied`、`DENIED` が記録される |
| US3-2(spec) | 失効した `rt_` で `POST /v1/runner/job-requests` | `401`。割り当てなし |
| US3-3(spec) | `rt_` で `POST /v1/jobs` | `403 permission_denied` |
| US4-1〜2(spec) | 偽の認証基盤でログイン、対応表を変更して `POST /v1/access/reload` | 次の呼び出しから新しい権限 |
| US5-1〜3(spec) | `GET /v1/jobs?state=…&submitter=…`、`cursor`、`GET /v1/queue` | 絞り込み、継ぎ目の重複・欠落なし、待機列の順 |
| US6-1〜2(spec) | `GET /v1/events` | 変更を受信、`Last-Event-ID` で補う、範囲外で `resync` |
| US7-1〜3(spec) | 各種の失敗 | `problem+json` の `code` と追加の項目 |
