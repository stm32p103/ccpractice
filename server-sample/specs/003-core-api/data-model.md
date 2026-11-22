# データモデル: コア API — コアを HTTP API として公開する

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **調査**: [research.md](research.md)

本 feature が加えるモデル(`job_core_api` の値・記録)と、永続化の表(`job_core_persistence`)を定める。
001・002 のドメインモデル(ジョブ、待機列、ランナー、リース、トークン、監査ログ)は変えない(追加は §6 だけ)。

---

## 1. 主体と認証

### `Principal`(001。再掲)

`subject_id`、`permissions`、`kind`(`HUMAN` / `SERVICE` / `RUNNER` / `SYSTEM`。本 feature で `ANONYMOUS` を加える。R10)。
API は、認証の結果として `Principal` を作り、コアのユースケースに渡す。**権限の判定には `kind` を使わない**(憲章 原則 9)。

### `VerifiedIdentity`(認証基盤のポートの結果)

| 項目 | 型 | 説明 |
|---|---|---|
| `subject_id` | `SubjectId` | 認証基盤が確認した本人の識別子(不透明な文字列。1〜256 文字) |
| `display_name` | `str \| None` | 表示名(画面用。1〜128 文字。権限の判定に使わない) |
| `groups` | `frozenset[str]` | 所属グループ(各 1〜256 文字、最大 128 個)。意味は解釈しない |

### `ServiceCredential`(サービス用の認証情報)

| 項目 | 型 | 説明 |
|---|---|---|
| `credential_id` | `str` | 一意(`IdGenerator`)。値と別の識別子。一覧・失効に使う |
| `name` | `str` | 1〜128 文字。失効していない認証情報の間で一意 |
| `subject_id` | `SubjectId` | 監査の `actor` になる識別子。`credential_id` から導く(`svc:<credential_id>`) |
| `permissions` | `frozenset[Permission]` | 付与した権限。設定の「サービスに付与できる権限の上限」の部分集合(R4) |
| `token_hash` | `TokenHash` | 値の SHA-256(16 進 64 文字)。値は保存しない |
| `created_at` | `datetime` | 発行日時 |
| `created_by` | `SubjectId` | 発行した主体 |
| `revoked_at` | `datetime \| None` | 失効日時。`None` = 有効 |
| `last_used_at` | `datetime \| None` | 最後に認証に成功した日時(丸めて更新。1 分に 1 回まで) |
| `version` | `int` | 楽観的排他 |

不変条件: 失効は取り消せない(再発行は新しい認証情報)。値は発行時の 1 度だけ返る。`repr`・ログ・例外・監査に、値とハッシュを含めない(R4)。

### `Session`(人間の利用者のセッション)

| 項目 | 型 | 説明 |
|---|---|---|
| `session_id` | `str` | 一意。値と別の識別子 |
| `token_hash` | `TokenHash` | 値(`ss_...`)の SHA-256 |
| `subject_id` | `SubjectId` | ログイン時に確認した本人 |
| `display_name` | `str \| None` | 表示名 |
| `groups` | `frozenset[str]` | **ログイン時の**所属グループ。権限は保存しない(呼び出しごとに導く。R5) |
| `created_at` | `datetime` | 作成日時 |
| `last_used_at` | `datetime` | 最後の利用日時(無操作の期限の起点。呼び出しごとに更新) |
| `expires_at` | `datetime` | 絶対期限 |
| `revoked_at` | `datetime \| None` | ログアウト・失効の日時 |

有効の判定: `revoked_at is None` かつ `now < expires_at` かつ `now - last_used_at < idle_timeout`。判定と `last_used_at` の更新は、1 回の照合で行う。
期限切れ・失効後の記録は、一定期間(既定 7 日)のあとに削除する(定期処理。R20)。

## 2. アクセスの設定

### `AccessConfig`(対応表。設定ファイルから読む。不変)

| 項目 | 型 | 説明 |
|---|---|---|
| `roles` | `Mapping[RoleName, frozenset[Permission]]` | ロール名(`^[a-z][a-z0-9_-]{0,31}$`)→ 権限 |
| `group_roles` | `Mapping[str, frozenset[RoleName]]` | 所属グループ → ロール |
| `default_roles` | `frozenset[RoleName]` | どの所属グループにも当たらない利用者のロール |
| `service_permission_ceiling` | `frozenset[Permission]` | サービス用の認証情報に付与できる権限の上限 |
| `digest` | `str` | 内容の正規化した SHA-256(変更の監査用) |

検証(読み込み時。失敗したら現在の `AccessConfig` を保つ。R6):
- 参照されるロールがすべて定義されている。権限の名前がすべて既知。
- **ロールに載せられない権限**(`job.execute`、`runner.report`、`retention.purge`、`runner.sweep`)を含まない。
- `service_permission_ceiling` が、上と同じ権限を含まない。
- `default_roles` が定義済みのロールだけを含む(空でもよい = 既定で何も許可しない)。

導出: `permissions_of(groups) = ⋃ roles[r] for r in (⋃ group_roles[g] for g in groups) or default_roles`。
所属グループが対応表に 1 つもなければ `default_roles`。1 つでも当たれば、当たったロールの和集合(`default_roles` は加えない)。

## 3. 変更の通知(イベント)

### `ChangeEvent`(SSE で配信。永続化しない)

| 項目 | 型 | 説明 |
|---|---|---|
| `seq` | `int` | 世代内で単調増加(1 から) |
| `epoch` | `str` | サーバーの起動ごとの世代の識別子。世代が違う `Last-Event-ID` は `resync`(R9) |
| `type` | `job.changed` / `runner.changed` / `queue.changed` / `resync` / `auth.expired` | — |
| `occurred_at` | `datetime` | UTC |
| `subject` | `{kind: "job" \| "runner", id}` \| なし | 対象。`resync`・`auth.expired` は持たない |
| `state` | `str \| None` | 変更後の状態(ジョブ: `queued` など、ランナー: `online` など) |
| `change` | 固定の語彙 | R9 |

**含めないもの**: payload、ログ、成果物、理由、異常の説明、能力の値、ジョブ定義の項目、提出者以外の個人に関わる自由な文字列(FR-018、T-A8)。
`queue.changed` は、待機列の順序が変わったこと(提出・位置指定・スケジュール変更・取り消し・割り当て)を示す。クライアントは `GET /v1/queue` を再取得する。

`ChangeBroker` は、直近 N 件(既定 1000)をリングバッファに持ち、購読者ごとに送信待ちの列(上限 100 件)を持つ。

## 4. エラー

### `Problem`(`application/problem+json`)

| 項目 | 型 | 説明 |
|---|---|---|
| `type` | `str` | `urn:job-api:error:<code>` |
| `title` | `str` | `code` ごとの固定の短い文 |
| `status` | `int` | HTTP の状態コード |
| `code` | `str` | コアの `code`、または API の `code`([contracts/http-api.md](contracts/http-api.md) §3) |
| `detail` | `str` | 原因の説明(固定の文面。秘密・他者の内容を含まない) |
| `request_id` | `str` | 要求の追跡用の識別子 |
| (追加の項目) | — | `code` ごとに固定。例: `required_permissions`、`existing_job_id`、`anchor_job_id`、`field`、`from_state`、`operation`、`errors` |

## 5. 永続化の表(core-persistence。Alembic で管理)

001・002 の表は、各ポートの契約から導く(列の詳細は実装の段階で決め、契約テストで検証する)。本 feature が加える表:

| 表 | 主な列 | 索引・制約 |
|---|---|---|
| `service_credentials` | `credential_id`(主キー)、`name`、`permissions`(配列)、`token_hash`、`created_at`、`created_by`、`revoked_at`、`last_used_at`、`version` | `token_hash` に一意の索引。`name` は `revoked_at IS NULL` の行の間で一意(部分一意索引) |
| `sessions` | `session_id`(主キー)、`token_hash`、`subject_id`、`display_name`、`groups`(配列)、`created_at`、`last_used_at`、`expires_at`、`revoked_at` | `token_hash` に一意の索引。`expires_at`・`revoked_at` に削除用の索引 |

- ジョブの検索(R8)のため、`jobs` に `(submitted_at DESC, job_id DESC)` の複合索引、`owner`・`state` の索引を加える。
- 監査ログの表は追記専用(更新・削除は保持期間の削除だけ。001 T-4)。`AuditOperation` の追加値(§6)は文字列として保存する。
- トークンの値・パスワード・認証基盤が返した生の応答は、どの表にも保存しない。

## 6. コア(001・002)への追加

001・002 の公開の振る舞いと受け入れテストを変えない、小さな追加に限る(plan「001・002 への変更」)。

| 追加 | 内容 | 出典 |
|---|---|---|
| `Permission.ACCESS_MANAGE` | `access.manage`(13 番目の権限) | R6 |
| `PrincipalKind.ANONYMOUS` | 認証に失敗した呼び出しの `actor_kind` | R10 |
| `AuditOperation` | `LOGIN`、`LOGOUT`、`AUTH_FAILED`、`SERVICE_CREDENTIAL_ISSUE`、`SERVICE_CREDENTIAL_REVOKE`、`ACCESS_CONFIG_CHANGE` | R10 |
| `SearchJobs`(問い合わせ)と `JobRepository.search` | 状態・提出者・提出日時の範囲の絞り込み、キーセットの頁送り | R8 |

## 7. 状態遷移

本 feature は、ジョブ・ランナーの状態遷移を新しく定めない(001・002 の規則に従う)。本 feature の状態遷移は次の 2 つだけ。

- **サービス用の認証情報**: 有効 → 失効(一方向)。
- **セッション**: 有効 → 失効(ログアウト、管理者による失効) / 期限切れ(絶対期限、無操作)。いずれも一方向。
