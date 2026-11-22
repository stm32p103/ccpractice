---

description: "コア API(003)の実装タスク"
---

# Tasks: コア API — コアを HTTP API として公開する

**Input**: `specs/003-core-api/` の設計文書

**Prerequisites**: [plan.md](plan.md)、[spec.md](spec.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md)

**Tests**: 含める。憲章 原則 11(権限の網羅、ポートの契約テストを Fake と実アダプタの両方で、GitHub なしの結合試験)と、spec の SC-001〜SC-010 がテストでの検証を求める。
各ストーリーでは、テストを先に書き、失敗することを確かめてから実装する。

**Organization**: ユーザーストーリーごとにフェーズを分け、ストーリー単位で実装・検証できるようにする。永続化と起動の入口(`core-persistence`、`core-server`)は、ストーリーに属さない横断のフェーズ(Phase 12)に置く。
ストーリーの検証は、メモリ上の Fake(憲章 原則 11)で行い、実 DB は Phase 12 で同じ契約テストを通す。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並行して実施できる(別のファイルで、未完了のタスクに依存しない)
- **[Story]**: 対応するユーザーストーリー(US1〜US9)
- パスはリポジトリのルートからの相対パス([plan.md の Source Code](plan.md#source-code-repository-root) の構成に従う)
- フィールドの制約は [data-model.md](data-model.md) が正。タスクでは `data-model.md` の `Entity.field` を引用し、制約を書き写さない
- 001・002 のコードへの変更は、plan.md「001・002 への変更」1〜6 に限る。001・002 の受け入れテスト(`core/tests/acceptance/**`)は変更せずに通り続けること
- 外部への通信は行わない(S2)。台帳の更新とレビューが済むまで、新しい取得先からの取得を実装しない(T002、T078)

---

## Phase 1: Setup(共通の基盤)

**Purpose**: 実装の前提条件(脅威モデル、台帳のレビュー)と、3 つのパッケージの初期化

- [X] T001 `docs/security/threat-model.md` に「3B 003 コア API」の節を追記する(憲章 S5・S6。**実装着手の前提条件**。plan.md Constitution Check の S5・S6 ⚠️)。research.md R18 の T-A1〜T-A12(脅威・対策・検査)と、残るリスク 3 点(所属グループの反映の遅れ、接続元の許可リストの限界、プロセスが 1 つであることへの依存)を書く。「実装との対応」の表(6 節)は、T097 で埋める
- [X] T002 [P] `inputs/13-security-egress.md` に、開発環境の構築スクリプトの取得先の追加案(PostgreSQL の公式の配布元。E15 の取得先)を「案(要レビュー)」として記し、レビューの依頼事項を残す(research.md R17)。**レビューの承認までは、T078 を着手しない**。E4・E16 の行が、本 feature の実装(ランナー向けのエンドポイントの範囲)と食い違わないことも確認する
- [X] T003 3 つのパッケージを作る: `core-api/pyproject.toml`、`core-persistence/pyproject.toml`、`core-server/pyproject.toml`(plan.md の依存。版は `uv.lock` で固定)と、空のパッケージ `core-api/src/job_core_api/{__init__,http/__init__,http/routers/__init__,access/__init__,events/__init__}.py`、`core-persistence/src/job_core_persistence/{__init__,repositories/__init__}.py`、`core-server/src/job_core_server/__init__.py`、各 `tests/` ディレクトリ。ルートの `pyproject.toml` の `[tool.uv.workspace].members`・`[tool.uv.sources]`・`[tool.ruff].src`・`[tool.mypy]`・`[tool.pytest.ini_options].testpaths` に追加し、`uv lock` と `uv sync` を実行する。開発依存に httpx、openapi-python-client、schemathesis を加える
- [X] T004 [P] `.importlinter` に契約を追加する(research.md R1): `api-independent-of-impl`(`job_core_api` は `job_core_persistence`・`job_core_server`・`job_testing` を import しない)、`persistence-independent-of-server`(`job_core_persistence` は `job_core_server` を import しない)、`core-independent-of-api`(`job_core` は `job_core_api`・`job_core_persistence`・`job_core_server` を import しない)。`root_packages` に 3 つを加える
- [X] T005 [P] `core/tests/architecture/forbidden_terms.txt`(禁止語の一覧)を `core-api` からも参照できるようにする(パスを共通化して `core-api/tests/architecture/` から読める形にする。語を増やさない)

**Checkpoint**: 脅威モデルに 003 の節があり、`uv sync` と `uv run lint-imports` が新しい契約を含めて通る(空のパッケージのため違反 0 件)

---

## Phase 2: Foundational(全ストーリーの前提)

**Purpose**: 001・002 への追加(権限・主体の種類・監査の操作)、設定・モデル・ポート、Fake と契約テスト、認証・エラー・ミドルウェアと、アプリの骨格

**⚠️ CRITICAL**: このフェーズが終わるまで、ユーザーストーリーの作業を始めない

### 001・002 への追加(共有部品)

- [X] T006 [P] 権限 `access.manage` を `core/src/job_core/access/permission.py` に追加する(plan.md「001・002 への変更」1、research.md R6)。`core/tests/unit/test_authorization.py` の権限の網羅を 13 種(8192 通り)に広げ、001・002 の既存の判定が変わらないことを確かめる
- [X] T007 [P] `PrincipalKind.ANONYMOUS` を `core/src/job_core/access/principal.py` に追加し、単体テスト(`core/tests/unit/test_principal.py` など既存のテストの場所に追記)で、可否の判定に `kind` が使われないことを確かめる(plan.md 同 2)
- [X] T008 [P] `AuditOperation` に `LOGIN`、`LOGOUT`、`AUTH_FAILED`、`SERVICE_CREDENTIAL_ISSUE`、`SERVICE_CREDENTIAL_REVOKE`、`ACCESS_CONFIG_CHANGE` を `core/src/job_core/job/domain/audit.py` に追加する(research.md R10)。`Denial.code` の説明に `identity_provider_unavailable` は含めない(拒否の記録ではなく API の応答だけ)。監査ログの契約テスト(`testing/src/job_testing/contracts/audit_outbox.py`)が新しい値を保存・検索できることを確かめる

### API の設定・モデル・ポート

- [X] T009 [P] 設定の値オブジェクト `ApiSettings` を `core-api/src/job_core_api/settings.py` に実装する(`allowed_networks`、`cors` は持たない、セッションの絶対期限・無操作の期限、Cookie の名前と `Secure`、許可する `Origin`、本文の上限、一覧の `limit`、SSE の接続数・再送の範囲・送信待ちの上限、認証失敗の記録の窓。既定値は research.md R5・R11・R19)。単体テスト `core-api/tests/unit/test_settings.py` で既定値と検証(不正な値の拒否)を確かめる
- [X] T010 [P] トークンの補助を `core-api/src/job_core_api/access/secrets.py` に実装する(`ss_`・`st_` の値の発行 = `secrets.token_urlsafe(32)` + 接頭辞、SHA-256 のハッシュ、`hmac.compare_digest` による比較、値の先頭による種類の判別)。ハッシュは `data-model.md` の `ServiceCredential.token_hash`・`Session.token_hash` の形に従う。単体テスト `core-api/tests/unit/test_secrets.py`(接頭辞の判別、値が `repr` に現れない、同じ値が同じハッシュ)
- [X] T011 [P] アクセス設定を `core-api/src/job_core_api/access/config.py` に実装する: `AccessConfig` と検証、`permissions_of(groups)`(和集合、対応がなければ `default_roles`)。項目と検証は `data-model.md` の `AccessConfig.roles`・`AccessConfig.group_roles`・`AccessConfig.default_roles`・`AccessConfig.service_permission_ceiling`・`AccessConfig.digest` に従う。単体テスト `core-api/tests/unit/test_access_config.py`(未定義のロールの参照、載せられない権限、上限、複数グループの和集合、`digest` が並び順に依らない、JSON Schema `contracts/access-config.schema.json` への適合)
- [X] T012 [P] モデルを `core-api/src/job_core_api/access/models.py` に実装する: `VerifiedIdentity`(`data-model.md` の `VerifiedIdentity.subject_id`・`VerifiedIdentity.display_name`・`VerifiedIdentity.groups`)、`ServiceCredential`(`ServiceCredential.credential_id`・`ServiceCredential.name`・`ServiceCredential.subject_id`・`ServiceCredential.permissions`・`ServiceCredential.token_hash`・`ServiceCredential.revoked_at`・`ServiceCredential.last_used_at`・`ServiceCredential.version`)、`Session`(`Session.session_id`・`Session.token_hash`・`Session.subject_id`・`Session.groups`・`Session.last_used_at`・`Session.expires_at`・`Session.revoked_at`)と、有効の判定の純粋な関数 `is_active(now, idle_timeout)`。`repr` にハッシュを含めない。単体テスト `core-api/tests/unit/test_access_models.py`
- [X] T013 ポートを `core-api/src/job_core_api/access/ports.py`(`IdentityProvider`、`LoginRedirect`、`IdentityRejected`、`IdentityProviderUnavailable`、`ServiceCredentialRepository`、`SessionRepository`、`AccessConfigSource`、`DuplicateCredentialName`、`AccessConfigInvalid`)と `core-api/src/job_core_api/events/ports.py`(`ChangeBroker`、`PendingChange`、`Subscription`)に実装する([contracts/ports.md](contracts/ports.md) の約束どおり)。`PendingChange` は、`type`・`subject`・`state`・`change` だけを持つ(自由な文字列の項目を持たない。T-A8)。**依存**: T012
- [X] T014 [P] Fake を `testing/src/job_testing/api_fakes/` に実装する: `FakeIdentityProvider`(試験が与える利用者・所属グループ。通信しない)、メモリ上の `ServiceCredentialRepository`・`SessionRepository`(`version` の衝突、失効の一方向)、メモリ上の `AccessConfigSource`(設定の値を差し替えられる)。**依存**: T013
- [X] T015 [P] 契約テストを `testing/src/job_testing/contracts/` に作成する(contracts/ports.md): `identity_provider.py`(`IdentityProviderContract`)、`service_credentials.py`(`ServiceCredentialContract`)、`sessions.py`(`SessionContract`)、`access_config.py`(`AccessConfigContract`)。Fake での実行を `testing/tests/test_api_fake_contracts.py` に置く。**依存**: T014
- [X] T016 API の層の監査を `core-api/src/job_core_api/access/audit.py` に実装する: 認証失敗の記録(`AUTH_FAILED`、actor `unauthenticated`、`ANONYMOUS`)と、同じ接続元・同じ種類の失敗の窓(既定 1 分)による抑制(窓の最初の 1 件を記録し、窓が閉じたとき件数つきの 1 件を追記。追記専用なので更新しない)。認証情報の値・ハッシュを記録しない。単体テスト `core-api/tests/unit/test_auth_audit.py`(窓の内外、件数、洪水で窓ごとに 2 件以内 = T-A7、値が現れない)。**依存**: T008、T009、T013
- [X] T017 認証を `core-api/src/job_core_api/access/authenticate.py` に実装する(research.md R4): 値の先頭で種類を判別し、`ss_` はセッションの記録から**現在の対応表で**権限を導いて `Principal`(`HUMAN`)を作り(無操作の期限の更新を含む)、`st_` はサービス用の認証情報から(`SERVICE`)、`rt_` は 002 の `AuthenticateRunner`(`RUNNER`)から作る。未知・失効・期限切れ・形式の誤りは同じ `AuthenticationFailed`(区別しない)。失敗を T016 で記録する。単体テスト `core-api/tests/unit/test_authenticate.py`(3 種の主体、失効の即時性、対応表の変更が次の呼び出しから効く、失敗の区別がない)。**依存**: T010〜T012、T016
- [X] T018 エラーの写像を `core-api/src/job_core_api/http/errors.py` に実装する(research.md R7、[contracts/http-api.md](contracts/http-api.md) §3): `Problem`(`data-model.md` の `Problem.type`・`Problem.title`・`Problem.status`・`Problem.code`・`Problem.detail`・`Problem.request_id`)、コア(001・002)の例外の種類ごとの写像の表、API の `code`、未知の例外は `500 internal_error`(詳細なし、内容は `request_id` つきでサーバーのログにだけ)。追加の項目は `code` ごとに固定。単体テスト `core-api/tests/unit/test_error_mapping.py`(001・002 のすべての例外の `code` が写像の表にあること、追加の項目が固定であること)
- [X] T019 ミドルウェアを `core-api/src/job_core_api/http/middleware.py` に実装する(research.md R10、R11): 接続元の許可リスト(認証より前に `403 network_not_allowed`。接続のアドレスだけを見る)、`X-Request-Id`、応答ヘッダ(`Cache-Control: no-store`(認証・セッションの応答)、`X-Content-Type-Options: nosniff`)、本文の上限(`413 payload_too_large`)、アクセスログ(メソッド・パス・状態コード・所要時間・`request_id`・主体の種類と識別子だけ。`Authorization`・Cookie・クエリ・本文を出さない)。単体テスト `core-api/tests/unit/test_middleware.py`
- [X] T020 認証の依存関係を `core-api/src/job_core_api/http/authn.py` に実装する: `Authorization: Bearer` と Cookie から値を取り出し(T017 を呼ぶ)、失敗は `401 authentication_failed`(`WWW-Authenticate: Bearer`)にする。Cookie で認証された、状態を変える呼び出し(POST/PUT/PATCH/DELETE)は、`Origin` が許可リストに一致しなければ `403 origin_not_allowed`(research.md R5。`Authorization` ヘッダには適用しない)。単体テスト `core-api/tests/unit/test_authn_dependency.py`。**依存**: T017、T018
- [X] T021 アプリの骨格を実装する: `core-api/src/job_core_api/app.py`(`create_app(deps)`、`/v1` のルーターの束、例外ハンドラー、ミドルウェアの登録)、`core-api/src/job_core_api/deps.py`(`ApiDependencies`: コアの依存、ポートの束、設定、時計)、`core-api/src/job_core_api/http/routers/health.py`(`GET /healthz`)。テスト用の組み立て `build_api()` を `testing/src/job_testing/api_fakes/build_api.py` に実装する(`build_core()` + api_fakes + `TestClient`、補助: `login_as(subject, groups)`(セッションを直接作る)、`issue_service_token(permissions)`、`runner_token()`)。結合テスト `core-api/tests/acceptance/test_skeleton.py`(`/healthz`、未認証は 401、許可外の接続元は 403)。**依存**: T014、T019、T020

**Checkpoint**: 認証・写像・ミドルウェアの単体テストと、Fake の契約テストがすべて通る。001・002 のテストが変更なしで通る。`build_api()` で、3 種類の主体の認証が通り、未認証が `problem+json` で拒否される

---

## Phase 3: User Story 1 - 生成したクライアントだけでジョブを提出・参照・管理する (Priority: P1) 🎯 MVP

**Goal**: 001・002 の操作(ジョブの提出・参照・スケジュール変更・取り消し・強制中断・やり直し、ランナーの管理、監査ログの参照)が、OpenAPI から生成したクライアントだけで行える

**Independent Test**: `build_api()` で、`login_as` した利用者として、生成クライアントだけを使い、提出から結果の参照、やり直しまでを一通り行う(WebUI・GitHub 連携の実装を使わない)

### Tests for User Story 1

- [X] T022 [P] [US1] US1-1〜4 の受け入れテストを `core-api/tests/acceptance/test_us1_jobs.py` に作成する(提出、位置指定、スケジュール変更、取り消し・強制中断(理由の必須)、やり直し、`Location`、実行中のジョブが変わらない。権限の不足は `403`)。テスト名に `us1_1` などのシナリオ番号を含める
- [X] T023 [P] [US1] ランナーの管理と監査ログの受け入れテストを `core-api/tests/acceptance/test_us1_runners_and_audit.py` に作成する(作成・一覧・詳細・経緯、maintenance・異常の解除・削除、トークンの再発行・失効(値は 1 度だけ)、許可リストの取得・置き換え、`GET /v1/audit-log` の絞り込み。権限のない主体は拒否される)
- [X] T024 [P] [US1] 生成クライアントによる受け入れ試験を作成する(SC-001、US1-5): `core-api/tests/acceptance/generated_client.py`(アプリの OpenAPI から `openapi-python-client` でクライアントを一時ディレクトリに生成する補助)と `core-api/tests/acceptance/test_generated_client.py`(**生成したクライアントだけ**で、提出 → 参照 → スケジュール変更 → 取り消し → 強制中断 → やり直し → ランナーの管理 → 監査ログの参照を行う。US1-5: 001・002 の各操作に対応する OpenAPI の操作が存在することの一覧検査を含む)

### Implementation for User Story 1

- [X] T025 [P] [US1] ジョブの要求・応答のモデルを `core-api/src/job_core_api/http/schemas_jobs.py` に実装する(`definition`、`placement`、`on_behalf_of`、`SubmitResult`、`RescheduleResult`、`CancelResult`、`JobDetail`、`AuditRecord`。001 の `JobSummaryView`・`JobDetailView` の写しで、payload を一覧の型に含めない)
- [X] T026 [P] [US1] ランナー・許可リスト・監査ログのモデルを `core-api/src/job_core_api/http/schemas_runners.py`・`core-api/src/job_core_api/http/schemas_audit.py` に実装する(`RunnerView`、`CreatedRunner`、`IssuedToken`、`AllowlistView`、監査の絞り込みのクエリ。トークンの値は発行の応答の型だけに置く)
- [X] T027 [US1] ジョブのルーターを `core-api/src/job_core_api/http/routers/jobs.py` に実装する: `POST /v1/jobs`、`GET /v1/jobs/{job_id}`、`GET /v1/jobs/{job_id}/history`、`POST /v1/jobs/{job_id}/reschedule`、`POST /v1/jobs/{job_id}/cancel`、`POST /v1/jobs/{job_id}/retry`([contracts/http-api.md](contracts/http-api.md) §2.2)。コアのユースケースに `Principal` を渡すだけで、権限・規則の判定を重複して持たない。**依存**: T025
- [X] T028 [US1] ランナーと許可リストのルーターを `core-api/src/job_core_api/http/routers/runners.py`・`core-api/src/job_core_api/http/routers/allowlist.py` に実装する(§2.3 の 12 エンドポイント)。**依存**: T026
- [X] T029 [US1] 監査ログのルーターを `core-api/src/job_core_api/http/routers/audit.py` に実装する(`GET /v1/audit-log`。§2.4)。**依存**: T026
- [X] T030 [US1] `core-api/src/job_core_api/app.py` に、上の 3 つのルーターを `/v1` の下に登録し、T022〜T024 を通す。**依存**: T027〜T029

**Checkpoint**: US1 の受け入れテストと、生成クライアントによる試験が通る

---

## Phase 4: User Story 2 - サービス主体が代理で提出する (Priority: P1)

**Goal**: 提出代行の権限を持つサービス主体だけが、別の提出者の名義で提出でき、監査ログに名義上の提出者と代理元が残る。サービス用の認証情報は、権限の上限の範囲で発行され、即時に失効できる

**Independent Test**: サービス主体と一般の利用者の両方で、`on_behalf_of` を付けて提出し、結果と監査ログを比べる

### Tests for User Story 2

- [X] T031 [P] [US2] US2-1〜4 の受け入れテストを `core-api/tests/acceptance/test_us2_service_delegation.py` に作成する(代理提出で名義上の提出者と代理元の両方が記録される、一般の利用者・提出代行のないサービス・ランナーは拒否、失効した認証情報は `401`、名義上の提出者が自分のジョブとして中断できる)
- [X] T032 [P] [US2] サービス用の認証情報のユースケースの単体テストを `core-api/tests/unit/test_service_credentials.py` に作成する(上限外の権限の拒否(T-A3)、同名の拒否と失効後の再利用、`access.manage` のない主体の拒否と記録、値は発行の応答だけ・以後どこにも現れない(property-based)、失効の一方向)

### Implementation for User Story 2

- [X] T033 [US2] サービス用の認証情報のユースケースを `core-api/src/job_core_api/access/credentials.py` に実装する(発行・一覧・失効。`data-model.md` の `ServiceCredential.name`・`ServiceCredential.permissions`・`ServiceCredential.subject_id`・`ServiceCredential.revoked_at` に従う。権限は設定の上限の部分集合に限る。`SERVICE_CREDENTIAL_ISSUE`・`SERVICE_CREDENTIAL_REVOKE` を `after` に権限の一覧だけを入れて記録(値・ハッシュは記録しない)。`access.manage` の拒否も記録)。**依存**: T008、T011、T012
- [X] T034 [US2] アクセスのモデルとルーターを `core-api/src/job_core_api/http/schemas_access.py`・`core-api/src/job_core_api/http/routers/access.py` に実装する(`POST /v1/service-credentials`、`GET /v1/service-credentials`、`DELETE /v1/service-credentials/{credential_id}`。§2.5 の前半)。**依存**: T033
- [X] T035 [US2] `core-api/src/job_core_api/app.py` にルーターを登録し、T031・T032 を通す。**依存**: T034

**Checkpoint**: US2 の受け入れテストが通る(サービスの代理提出と失効)

---

## Phase 5: User Story 3 - ランナーが自身の認証情報で API を使う (Priority: P1)

**Goal**: ランナーは自身のトークンで、ランナー用の操作だけを自身に関する対象に限って行える。失効したトークンではジョブを取得できない

**Independent Test**: 有効なランナーのトークンと失効させたトークンで、ジョブの取得を試みる。ランナーのトークンで、利用者向けの操作と他のランナーの情報を呼ぶ

### Tests for User Story 3

- [X] T036 [P] [US3] US3-1〜4 の受け入れテストを `core-api/tests/acceptance/test_us3_runner_protocol.py` に作成する(登録・生存通知・異常と回復・割り当ての要求・終了の報告・停止の確認の一巡、失効したトークンは `401` で割り当てられない、ランナーのトークンでジョブの提出・スケジュール変更・ランナーの管理が `403`、URL にランナーの識別子がなく他のランナーを対象にできない、人間・サービスの主体がランナー向けのエンドポイントを呼ぶと `403`)

### Implementation for User Story 3

- [X] T037 [P] [US3] ランナー向けのモデルを `core-api/src/job_core_api/http/schemas_runner_protocol.py` に実装する(`capabilities`(002 の申告のスキーマ)、`HeartbeatResult`、`JobRequestResult`(割り当てなしも結果)、`FinishResult`。割り当ての応答だけがジョブ定義(payload を含む)を持つ。research.md R16)
- [X] T038 [US3] ランナー向けのルーターを `core-api/src/job_core_api/http/routers/runner_protocol.py` に実装する(§2.6 の 7 エンドポイント。ランナーの識別子は URL に含めず、認証した `Principal.subject_id` を 002 のユースケースの `runner_id` として渡す)。**依存**: T037
- [X] T039 [US3] `core-api/src/job_core_api/app.py` にルーターを登録し、T036 を通す。**依存**: T038

**Checkpoint**: US3 の受け入れテストが通る。**P1(US1〜US3)の完了で、利用者・サービス・ランナーが API でジョブを回せる**

---

## Phase 6: User Story 4 - 人間の利用者を認証基盤で確認し、所属からロールを決める (Priority: P1)

**Goal**: 認証基盤(ポート)が確認した本人性と所属グループから、設定の対応表でロールと権限が決まり、対応表の変更が次の呼び出しから効く。偽の認証基盤で GitHub なしにログインして一連の操作を試験できる

**Independent Test**: 偽の認証基盤で、所属グループの異なる複数の利用者としてログインし、各権限の操作の可否を確認する。対応表を変えて再読み込みし、結果が変わることを確認する

### Tests for User Story 4

- [X] T040 [P] [US4] US4-1〜5 の受け入れテストを `core-api/tests/acceptance/test_us4_login_and_roles.py` に作成する(ログイン → 権限の導出、対応表の変更と再読み込み、どのロールにも当たらない利用者は `default_roles`、認証基盤が確認できない・利用できない(`401`・`503`)、API の定義と応答に認証基盤の名称がない、ログアウトと管理者による一括の失効、`return_to` の検査(T-A5)、ログインのたびに新しい値が発行される、Cookie での状態変更の `Origin` の検査、無操作・絶対期限での失効)
- [X] T041 [P] [US4] セッションのユースケースの単体テストを `core-api/tests/unit/test_sessions.py` に作成する(`data-model.md` の `Session.expires_at`・`Session.last_used_at`・`Session.revoked_at` に従う有効の判定、時計を進めた期限切れ、権限が保存されず導出されること)
- [X] T042 [P] [US4] TOML の `AccessConfigSource` の契約テストと不正な設定の試験を `core-api/tests/unit/test_access_config_file.py` に作成する(`AccessConfigContract` を TOML 実装に対して実行、未定義のロール・載せられない権限・上限外の権限・ファイルの欠落で `AccessConfigInvalid`(内容の抜粋を含まない))

### Implementation for User Story 4

- [X] T043 [P] [US4] TOML の `AccessConfigSource` を `core-api/src/job_core_api/access/config_file.py` に実装する(`tomllib`、呼び出しごとに読み直す。検証は T011 を使う)
- [X] T044 [US4] セッションのユースケースを `core-api/src/job_core_api/access/sessions.py` に実装する(ログイン = `IdentityProvider.complete_login` → セッションの作成、ログアウト、一括の失効、`LOGIN`・`LOGOUT` の監査、`IdentityRejected` は認証の失敗として T016 で記録、`IdentityProviderUnavailable` は `503`)。`data-model.md` の `VerifiedIdentity.groups`・`Session.groups` に従い、所属グループを保存して権限は保存しない。**依存**: T012、T013、T016
- [X] T045 [US4] 認証のルーターを `core-api/src/job_core_api/http/routers/auth.py` に実装する(`GET /v1/auth/login`、`GET /v1/auth/callback`、`POST /v1/auth/login`(`delivery = cookie | token`)、`GET /v1/auth/session`、`DELETE /v1/auth/session`。§2.1。Cookie は `__Host-session`・`HttpOnly`・`SameSite=Strict`・`Path=/`(`Secure` は設定。外す場合は名前 `session`)。`return_to` は同一オリジンの相対パスだけ(`400 return_to_invalid`)。認証・セッションの応答に `Cache-Control: no-store`)。**依存**: T044
- [X] T046 [US4] アクセスの設定の再読み込みを `core-api/src/job_core_api/access/config_reload.py` に実装し(読み込み → 検証 → 差し替え。検証に失敗したら現在の対応表を保つ。差し替えのたびに `ACCESS_CONFIG_CHANGE` を、変更前後の `AccessConfig.digest` とロール・グループの追加・削除・変更の差分で記録)、`core-api/src/job_core_api/http/routers/access.py` に `GET /v1/access/mapping`、`POST /v1/access/reload`(`400 access_config_invalid`)、`DELETE /v1/access/sessions?subject_id=` を追加する(§2.5 の後半。`access.manage`)。**依存**: T034、T043、T044
- [X] T047 [US4] `core-api/src/job_core_api/app.py` にルーターを登録し、`FakeIdentityProvider` の `proof`(`subject`・`groups`)で `POST /v1/auth/login` が通ることを確かめ、T040〜T042 を通す。**依存**: T045、T046

**Checkpoint**: US4 の受け入れテストが通る。**P1(US1〜US4)の完了 = MVP**: 偽の認証基盤だけで、GitHub なしに一連の操作を試験できる(SC-002)

---

## Phase 7: User Story 5 - 一覧の絞り込みとページ分割、キュー全体の参照 (Priority: P2)

**Goal**: ジョブの履歴を状態・提出者・期間で絞り込み、継ぎ目のない頁送りで取得でき、待機列は全員が順序つきで取得できる

**Independent Test**: 多数のジョブを作り、条件を変えて一覧を取得し、結果・順序・頁の継ぎ目(途中の削除・状態の変更を含む)を確認する

### Tests for User Story 5

- [X] T048 [P] [US5] `JobSearchContract` を `testing/src/job_testing/contracts/job_search.py` に作成する(contracts/ports.md「JobRepository.search」: 各条件の絞り込み、組み合わせ、頁の継ぎ目の重複・欠落なし(途中の削除・状態の変更を含む)、同時刻の順序、不正な `cursor`)。Fake での実行を `testing/tests/test_job_search_fake.py` に置く。**依存**: T052
- [X] T049 [P] [US5] US5-1〜3 の受け入れテストを `core-api/tests/acceptance/test_us5_listing.py` に作成する(`state`・`submitter`・`submitted_from`・`submitted_to` の絞り込み、`cursor` と `limit`(既定 50・最大 200)、頁の継ぎ目、`GET /v1/queue` の待機列の順序と `position`、全員が閲覧でき、閲覧が他の操作の権限を意味しない、payload が一覧に含まれない)

### Implementation for User Story 5

- [X] T050 [US5] `JobSearchCriteria` と `JobRepository.search` のポートを `core/src/job_core/job/application/ports.py` に追加する([contracts/ports.md](contracts/ports.md))。001 の他のポートは変えない
- [X] T051 [US5] `SearchJobs` の問い合わせを `core/src/job_core/job/application/queries/search_jobs.py` に実装し、`core/src/job_core/job/application/queries/__init__.py` から公開する(`general` の権限、`JobSummaryView` への変換、不正な `cursor` は `ValidationFailed("cursor", ...)`)。単体テスト `core/tests/unit/job/test_search_jobs.py`。**依存**: T050
- [X] T052 [US5] メモリ上の `JobRepository.search` を `testing/src/job_testing/core_fakes/`(ジョブのリポジトリの Fake。既存のファイルに追記)に実装し、`build_core()` の依存から `SearchJobs` を使えるようにする(plan.md 同 5)。**依存**: T050
- [X] T053 [US5] 一覧とキューのルーターを実装する: `core-api/src/job_core_api/http/routers/jobs.py` に `GET /v1/jobs`、`core-api/src/job_core_api/http/routers/queue.py` に `GET /v1/queue`(待機中の全件・順序つき・`position` つき)。`core-api/src/job_core_api/app.py` に登録し、T049 を通す。**依存**: T027、T051、T052

**Checkpoint**: US5 の受け入れテストと `JobSearchContract`(Fake)が通る。001・002 のテストが変更なしで通る

---

## Phase 8: User Story 6 - 状態の変更を購読して画面へ即時に反映する (Priority: P2)

**Goal**: クライアントが、ジョブ・ランナー・待機列の変更を SSE でほぼ即時に受け取り、再接続で取りこぼしを補える。通知に自由な文字列を含めない

**Independent Test**: 購読を開始し、別の主体でジョブの状態を変える。通知の届く時間と内容、再接続、切断を確認する

### Tests for User Story 6

- [X] T054 [P] [US6] `ChangeBrokerContract` を `testing/src/job_testing/contracts/change_broker.py` に作成する(contracts/ports.md「ChangeBroker」: `seq` の単調増加、バッファ内からの再送、範囲外・世代違いの `resync`、遅い購読者の切断と他の購読者への非影響、`PendingChange` に自由な文字列の項目がない)。実装(T056)に対する実行を `core-api/tests/unit/test_broker_contract.py` に置く
- [X] T055 [P] [US6] US6-1〜3 の受け入れテストを `core-api/tests/acceptance/test_events.py` に作成する(状態の変更の受信が通常の負荷で 3 秒以内(SC-007)、`Last-Event-ID` による補い、範囲外・サーバーの再起動(世代違い)で `resync`、失効・期限切れ・権限の喪失の 15 秒以内の検知と `auth.expired`、接続の上限で `503 sse_capacity_exceeded`、`topics` の絞り込み、通知にログ・payload・理由・異常の説明・能力の値が含まれない)
- [X] T056 [P] [US6] 通知のスキーマ検査を `core-api/tests/contract/test_change_event_schema.py` に作成する(発行されるすべての通知が [contracts/change-event.schema.json](contracts/change-event.schema.json) に適合する。変更の発生元(提出、位置指定、スケジュール変更、割り当て、完了、取り消し、中断の要求、やり直し、ランナーの作成・登録・online・offline・maintenance・異常・削除、リース切れ)ごとに 1 件以上)

### Implementation for User Story 6

- [X] T057 [US6] プロセス内のブローカーを `core-api/src/job_core_api/events/broker.py` に実装する(世代の識別子、リングバッファ(既定 1000)、購読者ごとの送信待ち(既定 100)、`publish` はブロックしない)。`data-model.md` の `ChangeEvent.seq`・`ChangeEvent.epoch` に従う。T054 を通す。**依存**: T013
- [X] T058 [US6] 通知の組み立てを `core-api/src/job_core_api/events/publisher.py` に実装する: ユースケースの**成功後**に、結果から `PendingChange` を作る写像の表(`data-model.md` の `ChangeEvent.type`・`ChangeEvent.change`・`ChangeEvent.state`・`ChangeEvent.subject` の語彙に従う。待機列の順序が変わる操作は `queue.changed` も)。失敗・拒否は発行しない。発行の失敗でユースケースの結果は変わらない。単体テスト `core-api/tests/unit/test_publisher.py`(写像の表が [contracts/http-api.md](contracts/http-api.md) の状態を変える操作を網羅する)。**依存**: T057
- [X] T059 [US6] SSE のエンドポイントを `core-api/src/job_core_api/events/sse.py`・`core-api/src/job_core_api/http/routers/events.py` に実装する(`GET /v1/events`、`hello`、15 秒ごとの `: keepalive`、そのたびに認証と `job.general` を再確認して `auth.expired`、`Last-Event-ID`、`topics`、接続の上限、送信待ちの超過で切断。§2.7)。**依存**: T057
- [X] T060 [US6] 既存のルーターに通知の発行を組み込む: `core-api/src/job_core_api/http/routers/jobs.py`、`runners.py`、`runner_protocol.py` で、状態を変えるユースケースの成功後に T058 を呼ぶ。**依存**: T058、T027、T028、T038
- [X] T061 [US6] 定期処理を `core-api/src/job_core_api/scheduler.py` に実装する(research.md R20): 固定の主体(`SYSTEM`、権限は `runner.sweep` と `retention.purge` だけ)で、`SweepRunners`(30 秒ごと)、`PurgeExpired`(1 日 1 回)、期限切れ・失効後のセッションの削除(既定 7 日。`SessionRepository.delete_inactive_before`)を実行し、結果を T058 経由で通知にも載せる。HTTP からは呼べない。単体テスト `core-api/tests/unit/test_scheduler.py`(手動で進める時計で、offline 化・リース切れ・削除・通知、冪等)。**依存**: T058
- [X] T062 [US6] `core-api/src/job_core_api/app.py` に、イベントのルーターの登録と、スケジューラーの起動・停止(アプリの起動・終了の処理。ワーカーが 1 つである前提)を加え、T054〜T056 を通す。**依存**: T059、T060、T061

**Checkpoint**: US6 の受け入れテストと `ChangeBrokerContract` が通る

---

## Phase 9: User Story 7 - 原因を判断できるエラーを機械可読な形式で受け取る (Priority: P2)

**Goal**: すべての失敗が `application/problem+json` で、原因を区別でき、開示してよい情報だけを含む

**Independent Test**: 各種の失敗を起こし、応答の `code` と追加の項目、開示の範囲を確認する

### Tests for User Story 7

- [X] T063 [P] [US7] 形式の契約テストを `core-api/tests/contract/test_problem.py` に作成する(応答が [contracts/problem.schema.json](contracts/problem.schema.json) に適合する、スキーマの `code` の列挙のすべてが写像の表にあり、各 `code` を起こす最小の操作が 1 つ以上ある、`code` ごとの状態コードが [contracts/http-api.md](contracts/http-api.md) §3.1 と一致する)
- [X] T064 [P] [US7] US7-1〜4 の受け入れテストを `core-api/tests/acceptance/test_us7_errors.py` に作成する(要件を満たすランナーなしの提出 = `422 no_eligible_runner`、権限不足 = `403`(`required_permissions`)、不正な遷移 = `409`(`from_state`・`operation`)、認証の失敗 = `401`(原因を区別しない)、重複 = `409`(`existing_job_id`)、形式の誤り = `400 request_invalid`(`errors` に値を含めない)、`413`、認証基盤の不通 = `503`)
- [X] T065 [P] [US7] 開示の検査を `core-api/tests/contract/test_problem_disclosure.py` に作成する(Hypothesis: 認証情報・payload・ログ・異常の説明・能力の値・内部の例外の文字列を入力に混ぜて失敗を起こしても、応答・アクセスログに現れない = T-A1・T-A8。未知の例外は `500 internal_error` で詳細なし)

### Implementation for User Story 7

- [X] T066 [US7] T063〜T065 の失敗を直す: `core-api/src/job_core_api/http/errors.py` で、`concurrency_conflict` に `Retry-After: 1`、`401` に `WWW-Authenticate: Bearer`、`request_invalid` の `errors` を位置と理由だけにする(値を含めない)、未知の例外の写像、`503` の写像を仕上げる。FastAPI の検証エラーを `request_invalid` に写す。`detail` を `code` ごとの固定の文面にする(例外の `str()` を使わない)。**依存**: T018

**Checkpoint**: US7 の受け入れ・契約・開示のテストが通る

---

## Phase 10: User Story 8 - API の定義から契約を確認し、バージョンで互換性を管理する (Priority: P2)

**Goal**: OpenAPI が実装から生成され、スナップショットと一致し、破壊的変更が検出され、実装が定義に適合する。URL に版が含まれる

**Independent Test**: 生成クライアントで一連の操作を行い(US1)、スナップショットの検査と schemathesis で、実装と定義の食い違いがないことを確かめる

### Tests for User Story 8

- [X] T067 [P] [US8] スナップショットの検査を `core-api/tests/contract/test_openapi_snapshot.py` に作成する(生成した OpenAPI が `core-api/openapi/openapi-v1.json` と一致する。差があれば、更新の手順(T070)を示して失敗する)
- [X] T068 [P] [US8] 破壊的変更の検査の単体テストを `core-api/tests/unit/test_openapi_compat.py` に作成する(パス・操作・応答の項目の削除、要求の必須項目の追加、型・列挙の縮小、認可の強化(`security` の変更)を検出し、項目・エンドポイントの追加と列挙値の追加は許す。research.md R3)
- [X] T069 [P] [US8] `schemathesis` の試験を `core-api/tests/contract/test_schemathesis.py` に作成する(Fake を配線したアプリに対し、認証つきで各エンドポイントの応答が定義に適合することを確認する(FR-003、SC-008)。状態を変えるエンドポイントは、テスト用の状態で実行する)
- [X] T070 [P] [US8] 版と語彙の検査を `core-api/tests/contract/test_versioning.py` に作成する(すべての業務のパスが `/v1/` で始まる、`info.version` のメジャーが 1、OpenAPI の文書全体(パス・説明・スキーマ名)にプラットフォーム・用途固有の語がない(共通の禁止語の一覧)、旧版の応答に `Deprecation`・`Sunset` を付けられる)

### Implementation for User Story 8

- [X] T071 [US8] 破壊的変更の検査を `core-api/src/job_core_api/tools/openapi_compat.py` に実装する(直前の公開版 `core-api/openapi/released/` との比較。公開版がなければ何もしない。T068 を通す)。外部のコマンドに依存せず、OpenAPI を JSON として比較する
- [X] T072 [US8] 版の扱いを実装する: `core-api/src/job_core_api/http/versioning.py`(版のプレフィックス `/v1`、`info.version`、旧版に `Deprecation`・`Sunset` ヘッダを付ける仕組み。設定で有効にする)、`GET /openapi.json` を認証つきにする(`core-api/src/job_core_api/app.py`。既定の公開を上書き)
- [X] T073 [US8] スナップショットの出力を `core-api/src/job_core_api/tools/export_openapi.py` に実装し、`core-api/openapi/openapi-v1.json` を生成してコミットする。T067・T069・T070 を通す。**依存**: T062(全ルーターの登録後)

**Checkpoint**: US8 の契約テストがすべて通る(SC-008)

---

## Phase 11: User Story 9 - 状態を変える呼び出しをすべて監査ログに残す (Priority: P2)

**Goal**: 状態を変えるすべての呼び出し(成功・拒否・認証の失敗)が、呼び出した主体(代理なら代理元も)とともに監査ログに残り、秘密が残らない

**Independent Test**: 各種の主体で、成功・拒否・認証失敗の呼び出しを行い、監査ログの内容を確認する

### Tests for User Story 9

- [X] T074 [P] [US9] US9-1〜4 の受け入れテストを `core-api/tests/acceptance/test_us9_audit.py` に作成する(成功した状態の変更に、主体の種類・識別子、日時、対象、操作の種類がある、代理に名義上の主体と代理元の両方がある、権限不足の拒否に拒否の事実と主体がある、認証の失敗に失敗の事実があり認証情報の値がない、`LOGIN`・`LOGOUT`・サービス用の認証情報・対応表の変更が記録される)
- [X] T075 [P] [US9] 網羅の検査を `core-api/tests/contract/test_audit_coverage.py` に作成する(OpenAPI の POST・PUT・DELETE の全操作が、監査の期待の表(操作 → 記録される `AuditOperation`、または「ログイン前の操作」などの理由つきの除外)に載っていること。載っていない操作があれば失敗する = FR-020 の抜けの検出)
- [X] T076 [P] [US9] アクセスログと `request_id` の検査を `core-api/tests/acceptance/test_logging.py` に作成する(ログに `Authorization`・Cookie・クエリ・本文が出ない、`X-Request-Id` が応答・`problem`・ログで一致する、要求に与えた `X-Request-Id` の形式の検査)

### Implementation for User Story 9

- [X] T077 [US9] T074〜T076 で見つかった不足を補う(`core-api/src/job_core_api/http/routers/*.py`、`core-api/src/job_core_api/access/*.py`)。補った監査の記録の項目は、001 FR-025 の項目で足りる範囲に収める(監査ログの項目を増やさない)

**Checkpoint**: US9 の受け入れテストと網羅の検査が通る。**P2(US5〜US9)の完了**

---

## Phase 12: 永続化と起動の入口(横断。ストーリーに属さない)

**Purpose**: `core-persistence`(SQLAlchemy + PostgreSQL)と `core-server`(組み立てと起動)を作り、同じ契約テストを実 DB で通す。ここまでのストーリーの検証は Fake で完結しているため、Phase 3〜11 と並行して進めてよい(契約テストのポートが固まった後)

- [X] T078 PostgreSQL の開発用インスタンスの構築を `ops/dev` に実装する(research.md R13、R17): `ops/dev/dev.config.psd1` に取得先・版・ハッシュ(SHA-256。公式の公開値で確認)を許可リストとして加え、`ops/dev/setup-dev.ps1` に、取得 → ハッシュの検証(不一致なら停止)→ ユーザー領域への展開 → 一時インスタンスの作成・起動・停止・撤去(`-WhatIf` でドライラン)を加える。Pester テストを `ops/dev/tests/setup-dev.Tests.ps1` に追加する(ハッシュの不一致で停止、許可リスト外の拒否、冪等性、撤去、ログに秘密がない)。**依存**: **T002 のレビューの承認**
- [X] T079 [P] `SecretSource` のポートを `core-api/src/job_core_api/secret_source.py` に定義し(contracts/ports.md)、環境変数の実装(開発・試験専用)を `core-server/src/job_core_server/secret_source_env.py` に実装する。契約テスト `core-server/tests/test_secret_source.py`(未知の名前で `SecretNotFound`、値・探した場所が例外・ログに出ない)
- [X] T080 [P] 表の定義を `core-persistence/src/job_core_persistence/models.py` に実装する(`data-model.md` §5: `service_credentials`、`sessions`、ジョブの検索用の索引。001・002 の表は各ポートの契約から導く)。`data-model.md` の `ServiceCredential.token_hash`・`Session.token_hash` の一意の索引、`ServiceCredential.name` の部分一意索引、`Session.expires_at`・`Session.revoked_at` の索引を含む
- [X] T081 Alembic の設定と最初のマイグレーションを `core-persistence/src/job_core_persistence/migrations/` に作成し、空の DB から最新まで適用できることを `core-persistence/tests/test_migrations.py`(`-m postgres`)で確かめる。**依存**: T080、T078
- [X] T082 `SqlUnitOfWork` と、001 のリポジトリ(ジョブ(`search` を含む)、待機列、監査ログ(追記専用)、アウトボックス)を `core-persistence/src/job_core_persistence/unit_of_work.py`・`core-persistence/src/job_core_persistence/repositories/{jobs,queue,audit,outbox}.py` に実装する(`version` の楽観的排他、衝突は `ConcurrencyConflict`)。**依存**: T081、T050
- [X] T083 [P] 002 のリポジトリ(ランナー、リース、トークン、許可リスト)と `RunnerCatalog` を `core-persistence/src/job_core_persistence/repositories/{runners,leases,tokens,allowlist,catalog}.py` に実装する(`RunnerUnitOfWork` を満たす)。**依存**: T082
- [X] T084 [P] サービス用の認証情報とセッションのリポジトリを `core-persistence/src/job_core_persistence/repositories/{service_credentials,sessions}.py` に実装する(`data-model.md` の `ServiceCredential.version`・`ServiceCredential.revoked_at`(一方向)・`Session.last_used_at`(巻き戻さない)に従う)。**依存**: T082
- [X] T085 契約テストを実 DB でも実行できるようにする(research.md R13): `testing/src/job_testing/contracts/` のフィクスチャを、Fake と SQLAlchemy の両方で実行できる形にし、`core-persistence/tests/test_contracts_postgres.py`(`-m postgres`)で 001・002・003 のすべての契約テスト(`UnitOfWork`、各リポジトリ、`JobSearchContract`、`ServiceCredentialContract`、`SessionContract`)を通す。`pyproject.toml` に `postgres` マーカーを追加する。**依存**: T082〜T084
- [X] T086 同時実行の試験を `core-persistence/tests/test_concurrency_postgres.py`(`-m postgres`)に作成する(割り当ての同時の要求で 1 件のジョブが 2 台に割り当てられない、スケジュール変更と取り消しの競合、002 の `RequestJob` の同時実行。001・002 の同時実行の受け入れテストと同じ観点)。**依存**: T083
- [X] T087 [P] `core-server` の設定を `core-server/src/job_core_server/settings.py` に実装する(TOML の読み込みと検証。`profile = "dev"` 以外では、Fake の認証基盤・メモリ上のリポジトリ・環境変数の `SecretSource` の選択を拒否または警告する = T-A9。bind するアドレス、`allowed_networks`、データベースの接続の指定。秘密は `SecretSource` から)。単体テスト `core-server/tests/test_settings.py`
- [X] T088 `core-server` の組み立てと起動を `core-server/src/job_core_server/wiring.py`・`core-server/src/job_core_server/__main__.py` に実装する(ポート実装の選択、`create_app` の呼び出し、`uvicorn` のワーカー数 1、`profile = "dev"` のメモリ構成)。単体テスト `core-server/tests/test_wiring.py`。**依存**: T087、T062、T085
- [X] T089 [P] 設定の雛形を `core-server/config/` に作成する(`server.example.toml`、`access.example.toml`(research.md R6 の汎用のロール名)、`server.dev.toml`、`access.dev.toml`)。秘密情報を含めない。`access.*.toml` が [contracts/access-config.schema.json](contracts/access-config.schema.json) と検証を通ることを `core-server/tests/test_config_templates.py` で確かめる
- [X] T090 実 DB での通しの試験を `core-server/tests/test_e2e_postgres.py`(`-m postgres`)に作成する(`FakeIdentityProvider` + PostgreSQL。生成クライアントで、提出 → ランナーの取得 → 終了 → やり直し。サービスの再起動(アプリの作り直し)後も、セッション・認証情報・ジョブが残る)。**依存**: T088
- [ ] T091 サーバーでの試行の項目を `ops/` に加える(憲章 原則 14。**009 の基盤(`setup-server.ps1`、`db/migrate.ps1`、`common/`)ができてから**): コア API のサービス登録(WinSW。自動起動・異常時の再起動)、`server.toml`・`access.toml` の配置と ACL、`migrate.ps1` からの Alembic、受信のファイアウォール規則、`verify/smoke-test.ps1` の項目([quickstart.md](quickstart.md) §4。マイグレーションの冪等、一巡、再起動後の永続)。009 の基盤が未着手の場合は、このタスクを保留とし、009 に項目として引き継ぐ(plan.md「他の feature への引き継ぎ」)

**Checkpoint**: 契約テストが Fake と PostgreSQL の両方で通り、実 DB の通しの試験が通る

---

## Phase 13: Polish & Cross-Cutting Concerns

**Purpose**: 横断の検査、文書の同期、quickstart の全検証

- [X] T092 [P] アーキテクチャの検査を `core-api/tests/architecture/test_imports.py`(`uv run lint-imports` を呼ぶ)・`core-api/tests/architecture/test_vocabulary.py`(`core-api` のソースと OpenAPI の文書に禁止語がない)・`core-api/tests/architecture/test_forbidden_apis.py`(`job_core_api`・`job_core_persistence` に `httpx`・`requests`・`urllib.request`・`http.client`・`aiohttp`・`socket` の直接の利用がない = research.md R12)に作成する
- [X] T093 [P] 外向きの通信の検査を `core-api/tests/acceptance/test_egress.py` に作成する(SC-009、FR-023・FR-024: 送信を記録する偽のサーバーと、外向きの接続の検知を用意し、ログイン・提出・購読・ランナーの一巡のあいだ、外向きの通信が 0 件。API が静的資産・外部のフォント・テレメトリを返さない・読まない)
- [X] T094 [P] 性能の目安を `core-api/tests/perf/test_api_perf.py`(`-m perf`)に作成する(SC-010: 50 人の同時の利用者で、提出・一覧・詳細・キューが 2 秒以内。認証の照合と権限の導出が 1 呼び出しあたり数ミリ秒の範囲。SSE の接続 200 での通知の遅延)
- [X] T095 [P] 認証・認可の網羅の検査を `core-api/tests/unit/test_authn_authz.py` に作成する(SC-005: 3 種類の主体 × 13 権限の部分集合 × 公開する各操作の可否が、権限だけで決まり、主体の種類で変わらない。拒否は 100% 監査ログに残る)
- [X] T096 [P] 偽の認証基盤の混入の検査を `core-server/tests/test_profile_guard.py` に作成する(T-A9: `profile != "dev"` で Fake・メモリ・環境変数の `SecretSource` を選ぶ設定は、起動が拒否される)。T087 の検証の抜けを補う
- [X] T097 `docs/security/threat-model.md` の「実装との対応」の表に、003 の T-A1〜T-A12 の実装箇所とテストを追記する(完了の時点の日付)。T001 で書いた残るリスクと矛盾がないことを確認する
- [X] T098 [P] 001・002 の契約文書を同期する: `specs/001-core-job-queue/contracts/application-api.md`(権限の表に `access.manage`、`SearchJobs`)、`specs/001-core-job-queue/contracts/ports.md`(`JobRepository.search`)、`specs/001-core-job-queue/data-model.md`・`specs/002-runner-management/contracts/application-api.md`(権限 13 種、`AuditOperation` の追加、`PrincipalKind.ANONYMOUS`)を、実装に合わせて更新する(振る舞いは変えない)
- [X] T099 `ops/dev/setup-dev.ps1` の `-VerifyOnly` に、quickstart.md の V19〜V28 を追加し、`ops/dev/tests/setup-dev.Tests.ps1` に「V1〜V28 を順に実行して一覧を表示する」「PostgreSQL が使えない場合、V26 を保留として報告する(他の検証は続ける)」ことの検査を追加する。**依存**: T078(V26 の実行)
- [X] T100 [P] `core-api/README.md`・`core-server/README.md` を作成する(起動と設定、`profile`、ポートの差し替えの方法、**API サーバーのプロセスが 1 つであること**、残るリスク(所属グループの反映の遅れ、接続元の許可リストの限界)、`/v1` の互換の方針)
- [X] T101 静的検査と網羅の確認: `uv run ruff check`、`uv run mypy`(strict)、カバレッジを実行し、`core-api` の認証・認可・エラーの写像・ブローカーの分岐が網羅されていることを確かめて、不足を直す
- [X] T102 [P] 書き出し台帳との最終の突き合わせ: `inputs/13-security-egress.md` の E4・E9〜E11・E15・E16 と、本 feature の実装(ランナー向けのエンドポイントの項目、通知の内容、PostgreSQL の取得先)を照合する。T002 のレビューの結果を台帳に反映する(承認された場合は E15 を更新し、「案」の記述を外す)
- [ ] T103 quickstart.md の V1〜V28 と §3 の手動のシナリオ(手順 1〜10)を実行し、結果を確認する。失敗があれば原因のタスクに戻って直す。001・002 の受け入れテストが変更なしで通ること、spec の受け入れ基準 4 件(quickstart.md §5)が満たされることを確かめる

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1(Setup)**: 依存なし。**T001(脅威モデル)を先に完成**。T002(台帳のレビュー依頼)は T078 の前に承認が要る
- **Phase 2(Foundational)**: Phase 1 の完了に依存。**すべてのストーリーをブロック**する
- **Phase 3〜11(User Stories)**: Phase 2 の完了に依存。下の「完了の順序」に従う
- **Phase 12(永続化と起動)**: Phase 2 の完了後、契約テストのポートが固まった時点から、ストーリーと並行して進められる(T078 は台帳のレビューに依存、T082 は T050(US5)に依存、T088 は T062(US6)に依存、T091 は 009 の基盤に依存)
- **Phase 13(Polish)**: 必要なストーリーと Phase 12 の完了に依存。T103 が最後

### User Story Dependencies(完了の順序)

- **US1**(P1)→ **US2**(P1): `routers/access.py` を US4 が拡張するため、US2 → US4 の順
- **US3**(P1): Phase 2 の後、US1 と独立に実施できる(`app.py` の登録だけが共通)
- **US4**(P1): US2(`routers/access.py`、`access/config.py`)の後
- **US5**(P2): US1 の後(`routers/jobs.py` に追加)。コアの `SearchJobs` は独立
- **US6**(P2): US1・US3 の後(通知の発行を既存のルーターに組み込む)。ブローカーと SSE は独立
- **US7**(P2): Phase 2(`errors.py`)の後なら、いつでも実施できる。全ルーターが出揃った後に実施すると、`code` の網羅の検査が効く
- **US8**(P2): **US1〜US7 のルーターの登録後**(T073 のスナップショットは、全エンドポイントが出揃ってから)
- **US9**(P2): US2・US4・US6 の後(網羅の検査は全エンドポイントが前提)

### Within Each User Story

- テストを先に書き、失敗を確かめてから実装する
- モデル/スキーマ → ユースケース/補助 → ルーター → 登録 → 受け入れテスト
- `[P]` のタスクは、別のファイルで並行して実施できる

### Parallel Opportunities

- Phase 1: T002、T004、T005 は並行
- Phase 2: T006〜T008(コアへの追加)、T009〜T012 は並行。T014・T015 は T013 の後に並行
- US1: T022〜T024(テスト)、T025・T026(モデル)は並行。US3: US1 と並行して実施できる
- US5〜US9 のテスト(T048・T049、T054〜T056、T063〜T065、T067〜T070、T074〜T076)は、それぞれのストーリー内で並行
- Phase 12: T079・T080・T087・T089 は並行。T083・T084 は T082 の後に並行

## Parallel Example: Foundational

```text
Task: "T006 権限 access.manage の追加 core/src/job_core/access/permission.py"
Task: "T007 PrincipalKind.ANONYMOUS の追加 core/src/job_core/access/principal.py"
Task: "T008 AuditOperation の追加 core/src/job_core/job/domain/audit.py"
Task: "T009 ApiSettings core-api/src/job_core_api/settings.py"
Task: "T011 AccessConfig core-api/src/job_core_api/access/config.py"
```

## Parallel Example: User Story 1

```text
Task: "T022 US1 の受け入れテスト core-api/tests/acceptance/test_us1_jobs.py"
Task: "T023 ランナー管理・監査ログの受け入れテスト core-api/tests/acceptance/test_us1_runners_and_audit.py"
Task: "T024 生成クライアントの試験 core-api/tests/acceptance/test_generated_client.py"
Task: "T025 ジョブのモデル core-api/src/job_core_api/http/schemas_jobs.py"
Task: "T026 ランナー・監査のモデル core-api/src/job_core_api/http/schemas_runners.py"
```

## Parallel Example: Phase 2 完了後

```text
開発者 A: US1 → US2 → US4(P1。routers/access.py を引き継ぐ)
開発者 B: US3(ランナー向けのエンドポイント。US1 と独立)
開発者 C: Phase 12 の T079・T080・T087・T089(契約テストのポートが固まった後)
```

---

## Implementation Strategy

### MVP First(User Story 1〜4)

003 は、WebUI(006)・GitHub 連携(005)・ランナーエージェント(004)がコアを使うための入口である。P1 の 4 つのストーリーで、利用者・サービス・ランナーの 3 種類の主体が、認証・認可つきで一連の操作をできる。MVP は P1 全体とする。

1. Phase 1: Setup(**T001 脅威モデルの追記を先に完成**。T002 の台帳のレビュー依頼も早めに出す)
2. Phase 2: Foundational(すべてのストーリーをブロック)
3. Phase 3〜6: US1 → US2 → US3(並行可)→ US4
4. **STOP and VALIDATE**: `uv run pytest core-api/tests/acceptance core-api/tests/unit testing/tests` と、001・002 の全テスト、`uv run lint-imports` が通ることを確認(偽の認証基盤だけで一連の操作 = SC-002)

### Incremental Delivery

1. Setup + Foundational → 基盤が完成
2. US1〜US4 → 検証(MVP: 3 種類の主体と偽の認証基盤で、API の一連の操作)
3. US5 → 検証(履歴の検索と待機列。006 の一覧の前提)
4. US6 → 検証(SSE。006 の画面の更新の前提)
5. US7、US8、US9 → 検証(エラー、契約、監査)
6. Phase 12(永続化と起動)→ 契約テストを実 DB で通す。サーバーでの試行は 009 の基盤の後
7. Polish → `setup-dev.ps1 -VerifyOnly` で quickstart の全検証

### Parallel Team Strategy

1. 全員で Setup + Foundational
2. その後: A が US1 → US2 → US4、B が US3 → US6 の SSE、C が Phase 12(PostgreSQL・永続化)
3. P1 の完了後: US5、US7、US8、US9 を分担
4. 最後に Phase 13(T103 は全員で)

---

## Notes

- `[P]` = 別のファイルで、未完了のタスクに依存しない
- `[USn]` = spec のユーザーストーリーへの対応(Phase 12 の横断のタスクにはストーリーの印を付けない)
- 受け入れテストの名前に spec のシナリオ番号(`us2_1` など)を含め、spec との対応を追えるようにする
- フィールドの制約は data-model.md を正とし、タスクやコードのコメントに書き写さない
- 用途・プラットフォームの語を `core-api`・OpenAPI に入れない(T070、T092 が検出する)。テストの能力のキーは記号(`k1`、`set1`)を使う
- 認証情報の値・ハッシュをログ・例外・`repr`・応答・監査に出さない(T010、T016、T033、T065、T076 が検出する)
- 外部への通信を行わない。新しい取得先は、台帳のレビューの承認の後に実装する(T002、T078、T102)
- タスクまたは論理的なまとまりごとにコミットする

## 実装の状況(2026-11-22。2 回目の `/speckit-implement` の時点)

- **完了**: Phase 1〜11、Phase 12 のうち T079・T080〜T090、Phase 13 のうち T092〜T102。メモリ上の Fake(`profile = "dev"`)と PostgreSQL(SQLAlchemy 2.0 + psycopg3 + Alembic。集約は JSONB の文書 + 検索・一意性用の列)の両方で、001・002・003 の契約テストが通る。
- **未了**:
  - **T078**(完了。T002 の承認後): `setup-dev.ps1 -WithPostgres`。取得はハッシュ未固定のため停止する状態(`PostgreSql.Sha256` の固定が残る)。また、既存の `initdb`(PATH)・`JOB_TEST_POSTGRES_DSN` で V26 を実行できる(`job_testing.pg_fixtures`。取得しない)。
  - **T091**(サーバーでの試行): 009 の基盤が前提。
  - **T103**(V1〜V28 と手動のシナリオの通し): T078 の承認後の V26 の通し、および T091 の後。現時点の結果は完了報告に記載。
- 実装中に見つけて対処した点: FastAPI の組み込みのテレメトリの無効化(S2)、405 の `Allow` の正確さ、`cursor` が不正なときの 500(契約テストに追加)、日時の数値(UNIX 時刻)の受け付け、`job_type` の必須化。
- 永続化の設計: 楽観的排他(`version` 列を条件にした UPDATE。変更のない集約は `FOR SHARE` で確認)、一意性は部分一意索引(ランナー名・ジョブごと/ランナーごとの ACTIVE なリース・ランナーごとの有効なトークン・認証情報の名前とハッシュ)、衝突・デッドロックは `ConcurrencyConflict`。`search` は、UoW の未確定の変更を重ねない(確定した状態だけを読む)。
