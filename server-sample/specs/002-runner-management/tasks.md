---

description: "コア — ランナーとジョブの割り当ての管理(002)の実装タスク"
---

# Tasks: コア — ランナーとジョブの割り当ての管理(最小版)

**Input**: `specs/002-runner-management/` の設計文書

**Prerequisites**: [plan.md](plan.md)、[spec.md](spec.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md)

**Tests**: 含める。憲章 原則 11(ドメイン層の単体テスト必須、状態遷移と権限の網羅、ポートの契約テスト)と、spec の SC-001・SC-002・SC-006〜SC-010・SC-012 がテストでの確認を求めているため。
各ストーリーでは、テストを先に書き、失敗することを確かめてから実装する。

**Organization**: ユーザーストーリーごとにフェーズを分け、ストーリー単位で実装・検証できるようにする。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並行して実施できる(別のファイルで、未完了のタスクに依存しない)
- **[Story]**: 対応するユーザーストーリー(US1〜US7)
- パスはリポジトリのルートからの相対パス([plan.md の Source Code](plan.md#source-code-repository-root) の構成に従う)
- フィールドの制約は [data-model.md](data-model.md) が正。タスクでは `data-model.md` の `Entity.field` を引用し、制約を書き写さない
- 001 のコードへの変更は、plan.md「001 への変更」1〜5 に限る。001 の受け入れテスト(`core/tests/acceptance/test_us*.py`)は変更せずに通り続けること

---

## Phase 1: Setup(共通の基盤)

**Purpose**: 実装の前提条件(脅威モデルの追記)と、runner コンテキストの初期化

- [X] T001 `docs/security/threat-model.md` に「002 ランナー管理」の節を追記する(憲章 S5・S6。**実装着手の前提条件**。plan.md Constitution Check の S5・S6 ⚠️)。research.md R18 の項目(トークンの漏えい・再利用、別のランナーへのなりすまし、能力の偽りの申告 = 許可リストは値の正しさを保証しない残るリスク、機材の異常の偽りの申告、異常の説明を経由した持ち出し、生存通知の大量送信)を、001 の節と同じ「誰を信頼するか・何から守るか・対策(どのタスクで担保するか)・残るリスク」の形で記す。§6「実装との対応」の 002 の行は空欄で置く
- [X] T002 空のパッケージ `core/src/job_core/runner/{__init__,domain/__init__,application/__init__,application/commands/__init__,application/queries/__init__}.py` と、テストのディレクトリ `core/tests/unit/runner/__init__.py`、`core/tests/acceptance/runner/__init__.py`(conftest は T030 で作る)を作成する。plan.md Source Code。T001 に依存
- [X] T003 [P] `.importlinter` に契約を追加する: `runner-layers`(`job_core.runner.application` → `job_core.runner.domain` の layers)、`job-independent-of-runner`(`job_core.job` は `job_core.runner` を import しない forbidden)。research.md R1、R15-1。T001 に依存
- [X] T004 [P] `ops/dev/setup-dev.ps1` の `-VerifyOnly` に quickstart.md の V12〜V18 を追加し、`ops/dev/tests/setup-dev.Tests.ps1` に「V1〜V18 を順に実行して一覧を表示する」ことの検査を加える。新しい取得先・依存は加えない(research.md R17)。T001 に依存

**Checkpoint**: 脅威モデルに 002 の節があり、`uv run lint-imports` が新しい契約を含めて通る(空のパッケージのため違反 0 件)

---

## Phase 2: Foundational(全ストーリーの前提)

**Purpose**: 001 への変更(権限・監査)、値オブジェクト、照合、4 つの集約、ポート、ランナーの認証、Fake、契約テスト

**⚠️ CRITICAL**: このフェーズが終わるまで、ユーザーストーリーの作業を始めない

### 001 への変更(共有部品)

- [X] T005 [P] ポート `SecretGenerator` を `core/src/job_core/shared/ports.py` に追加し、既定の実装 `SystemSecretGenerator`(`secrets.token_urlsafe(32)` に接頭辞 `rt_`)を `core/src/job_core/shared/secret_generator.py` に実装する(標準ライブラリの `secrets` と同名のモジュールを作らない)。contracts/ports.md「SecretGenerator」、research.md R9
- [X] T006 [P] 権限 `runner.manage`・`runner.report`・`runner.sweep` を `core/src/job_core/access/permission.py` に追加する(data-model.md §6。research.md R10)。001 の網羅テスト `core/tests/unit/test_authorization.py` は全権限の部分集合を列挙しているため 4096 通りに広がる。001 の判定の期待値は変えない(追加の権限は 001 のユースケースの可否に影響しない)ことを確認する。あわせてテストの実行時間を計測し、CI で 60 秒を超える場合は、追加の 3 権限を「すべて持つ/すべて持たない」の 2 通りにまとめて掛け合わせる(権限ごとの単独の検査は残す)
- [X] T007 監査ログの拡張を `core/src/job_core/job/domain/audit.py` に実装する: `AuditRecord.runner_id`(既定 `None`)、`AuditOperation` に research.md R14 の 15 種、`Denial.code` の値 `authentication_failed`・`invalid_declaration`(data-model.md §7)。あわせて `core/src/job_core/job/application/ports.py` の `AuditLog.query` の条件に `runner_id` を加え、`testing/src/job_testing/core_fakes/repositories.py` の Fake の AuditLog と `testing/src/job_testing/contracts/audit_outbox.py` の契約テスト(`runner_id` での絞り込み)を更新する。plan.md「001 への変更」2

### runner ドメイン(テスト → 実装)

- [X] T008 [P] 値オブジェクトの単体テストを `core/tests/unit/runner/test_values.py` に作成する(data-model.md §1 の `RunnerName`、`CapabilityKey`、`CapabilityValue`、`Capabilities`、`FaultDescription`、`TokenHash`、`RunnerTimingPolicy.heartbeat_interval`・`RunnerTimingPolicy.offline_after`・`RunnerTimingPolicy.lease_duration` の境界値。`RunnerTimingPolicy` の 2 倍の規則の違反は設定エラー)
- [X] T009 [P] ドメインの例外を `core/src/job_core/runner/domain/errors.py` に実装する(contracts/application-api.md の `RunnerNotFound`、`DuplicateRunnerName`、`RunnerDeleted`、`RunnerNotRegistered`、`AlreadyInMaintenance`、`NotInMaintenance`、`RunnerHasUnfinishedJob`、`InvalidDeclaration(violations)`、`InvalidRequirement(reason)`、`LeaseExpired`、`InvalidLeaseTransition`、`RunnerAuthenticationFailed`)。001 の `JobCoreError` を基底とし、`code` を持たせる。`InvalidDeclaration` の `violations` は「キーと理由」だけで、申告された値を含めない
- [X] T010 値オブジェクトを `core/src/job_core/runner/domain/values.py` に実装する(data-model.md の `RunnerName`、`CapabilityKey`、`CapabilityValue`(`SingleValue` / `SetValue`)、`Capabilities`、`ValueKind`、`FaultDescription`、`TokenHash`、`RunnerTimingPolicy.heartbeat_interval`・`.offline_after`・`.lease_duration`)。違反は 001 の `ValidationFailed(field, detail)`。T008 を通す
- [X] T011 [P] 照合の単体テストを `core/tests/unit/runner/test_matching.py` に作成する: 5 種の比較(`Op` の全値)× 1 つの値/集合 × キーの有無 × 能力側の型の不一致(満たさない)、要件側の文法のエラー(未知の `op`、指定値の形の不一致、数値・版として解釈できない値 → `InvalidRequirement`)、空の `all`、版の末尾の 0 の補い(`1.2` = `1.2.0`)。Hypothesis で版・数値の比較の性質(反射・反対称・推移)を検査する。research.md R2、R16。spec SC-001
- [X] T012 照合の純粋関数を `core/src/job_core/runner/domain/matching.py` に実装する: `parse_requirement(RunnerRequirement) -> ParsedRequirement`(data-model.md の `ParsedRequirement`、`Condition.key`・`Condition.op`・`Condition.operand`、`VersionTuple`。正準化済みの JSON 文字列を鍵にメモ化)、`satisfies(Capabilities, ParsedRequirement) -> bool`。数値は `decimal.Decimal`。research.md R2、R3。T010・T011 を通す
- [X] T013 要件の JSON Schema と照合の実装の一致を検査する契約テストを `core/tests/contract/test_runner_requirement_schema.py` に作成する。**依存**: T012・T014・T018(T018 の後に実施する)。次の 2 つに分ける。(1) 一致の検査: パッケージ内のスキーマ(`core/src/job_core/runner/schemas/`、T014)を使い、Hypothesis で生成した要件について、`runner_requirement.v1.json` に適合する ⇔ `parse_requirement` が成功することを確かめる。能力の申告も、`capability_declaration.v1.json` に適合する形の検査と T018 の `CapabilityAllowlist.validate` の形の検査が一致することを確かめる。(2) 同一性の検査: パッケージ内の 2 ファイルが `specs/002-runner-management/contracts/` の同名のスキーマ(`runner-requirement.schema.json`、`capability-declaration.schema.json`)と内容が同一であることだけを、別のテスト関数で比較する(`specs/` を読むのはこの関数だけ)
- [X] T014 [P] JSON Schema を `core/src/job_core/runner/schemas/runner_requirement.v1.json`、`core/src/job_core/runner/schemas/capability_declaration.v1.json` に配置する(`specs/002-runner-management/contracts/` の 2 ファイルと同一内容。パッケージのデータとして読めるよう `core/pyproject.toml` に含める)
- [X] T015 [P] `Runner` の単体テストを `core/tests/unit/runner/test_runner.py` に作成する: 状態の導出 `state_at` の優先順(data-model.md §2 の表)の全組み合わせ(`Runner.maintenance` × `Runner.fault` × `Runner.registered_at` の有無 × `now - Runner.last_seen_at` が `offline_after` の前後 × `Runner.deleted_at`)、各メソッドの事前条件と例外、`mark_connectivity` が変化の有無を返すこと、`report_fault` の再申告は説明と最終更新だけを変えること
- [X] T016 `Runner` 集約を `core/src/job_core/runner/domain/runner.py` に実装する(data-model.md §2 の `Runner.runner_id`、`.name`、`.created_at`、`.capabilities`、`.registered_at`、`.last_seen_at`、`.recorded_connectivity`、`.maintenance`、`.fault`、`.deleted_at`、`.version`、`RunnerState`、`state_at`、操作の表のメソッド)。T015 を通す
- [X] T017 [P] `CapabilityAllowlist` の単体テストを `core/tests/unit/runner/test_allowlist.py` に作成する(空の既定ですべて拒否、リスト外のキー、`ValueKind` の不一致、research.md R2 の長さ・文字の制限の違反、複数の違反をまとめて返すこと、`violations` に値が含まれないこと)。research.md R12
- [X] T018 `CapabilityAllowlist` 集約を `core/src/job_core/runner/domain/allowlist.py` に実装する(data-model.md §3 の `CapabilityAllowlist.entries`、`.version`、`validate`、`replace`)。T017 を通す
- [X] T019 [P] `Lease` の単体テストを `core/tests/unit/runner/test_lease.py` に作成する(data-model.md §4「遷移」の表の全行、`is_live_at` の期限ちょうどの境界、`EXPIRED` / `ENDED` からの遷移の拒否)
- [X] T020 `Lease` 集約を `core/src/job_core/runner/domain/lease.py` に実装する(data-model.md §4 の `Lease.lease_id`、`.job_id`、`.runner_id`、`.granted_at`、`.expires_at`、`.last_extended_at`、`.status`、`.version`)。T019 を通す
- [X] T021 [P] `RunnerToken` の単体テストを `core/tests/unit/runner/test_token.py` に作成する(ハッシュが SHA-256 の 16 進 64 文字であること、照合が `hmac.compare_digest` によること、`repr` / `str` / 例外のメッセージにハッシュが現れないこと、失効済みの扱い)
- [X] T022 `RunnerToken` 集約とハッシュの関数を `core/src/job_core/runner/domain/token.py` に実装する(data-model.md §5 の `RunnerToken.token_id`、`.runner_id`、`.token_hash`、`.issued_at`、`.revoked_at`。`IssuedToken(token_id, value)`)。research.md R9。T021 を通す

### runner アプリケーション層の基盤

- [X] T023 ポートを `core/src/job_core/runner/application/ports.py` に定義する(contracts/ports.md の `RunnerUnitOfWork`、`RunnerRepository`、`LeaseRepository`、`RunnerTokenRepository`、`CapabilityAllowlistRepository`、`RunnerCatalog`)と、依存の束 `RunnerDependencies`(001 の `CoreDependencies` の項目に、`RunnerUnitOfWork` のファクトリ、`RunnerCatalog`、`SecretGenerator`、`RunnerTimingPolicy` を加える)。ランナー用ユースケース共通の出力の型 `HeartbeatResult`(contracts/application-api.md。`state`、`lease_expires_at`、`heartbeat_interval`)も `core/src/job_core/runner/application/results.py` にここで定義する(US1 の `RegisterRunner` と US5 の異常の申告が使うため)
- [X] T024 [P] runner の権限の判定の網羅テストを `core/tests/unit/runner/test_authorization.py` に作成する(12 権限の全部分集合 × ユースケース。contracts/application-api.md の各ユースケースの必要な権限。`RequestJob` は `runner.report` と `job.execute` の両方。`runner.manage` は `audit.read_all` を含まず逆も同じ)。あわせて `AuthenticateRunner`(T026)が返す主体の権限が `{runner.report, job.execute}` の 2 つだけであること、その主体では `CreateRunner`・`SetMaintenance`・`DeleteRunner`・`ReplaceCapabilityAllowlist`・001 の `SubmitJob` がすべて `PermissionDenied` になることを、`core/tests/unit/runner/test_authenticate.py` で検査する(spec FR-025)。spec SC-009
- [X] T025 可否の純粋な関数を `core/src/job_core/runner/application/authorization.py` に実装する(`authorize_manage`、`authorize_report`、`authorize_request_job`、`authorize_sweep`、`authorize_view`、および `runner_id` と `principal.subject_id` の一致の検査 `require_self`(不一致は 001 の `RunnerMismatch`))。001 の `audit_support.audited_denials` を使い、拒否を記録する。T024 を通す
- [X] T026 ランナーの認証 `AuthenticateRunner` を `core/src/job_core/runner/application/commands/authenticate.py` に実装する(contracts/application-api.md「AuthenticateRunner」。返す主体の権限は `{runner.report, job.execute}` に固定。未知・失効・削除済みは区別せず `RunnerAuthenticationFailed`、監査に `RUNNER_AUTHENTICATE` の `DENIED`。トークンの値・ハッシュを記録しない)。T024 の `test_authenticate.py`(返す主体の権限の検査)を先に書いて失敗を確かめてから実装する。research.md R9
- [X] T027 [P] Fake のリポジトリを `testing/src/job_testing/core_fakes/runner_repositories.py` に実装する(`RunnerRepository`、`LeaseRepository`、`RunnerTokenRepository`、`CapabilityAllowlistRepository`、`RunnerCatalog`)。001 の Fake の UoW(`testing/src/job_testing/core_fakes/repositories.py`)を拡張して `RunnerUnitOfWork` を満たす(コミット直前の割り込みのフックを含む)。決定的な `FakeSecretGenerator` を `testing/src/job_testing/core_fakes/clock_ids.py` に追加する
- [X] T028 [P] 002 のポートの契約テスト群を `testing/src/job_testing/contracts/runner_persistence.py` に作成する(contracts/ports.md「契約テストの一覧」の 6 群。data-model.md §8 の不変条件 1・3・4 を含む)
- [X] T029 契約テストを Fake に対して実行する `testing/tests/test_runner_contracts_fake.py` を作成する。T027・T028 に依存
- [X] T030 受け入れテストの共通のフィクスチャを `core/tests/acceptance/runner/conftest.py` に作成する(Fake をつないだ `RunnerDependencies`、手動で進める時計、主体の作り方(`runner.manage` + `job.general` の管理者、`runner.sweep` の定期処理、`AuthenticateRunner` で得るランナー)、能力のキーは記号(`k1`、`set1`))

**Checkpoint**: 照合・集約・権限の単体テストと、Fake の契約テストがすべて通る。001 のテストが変更なしで通る

---

## Phase 3: User Story 1 - ランナーを作成し、ランナーが起動時に登録する (Priority: P1) 🎯 MVP

**Goal**: 権限を持つ利用者がランナーを作成してトークンを受け取り、ランナーが許可リストの能力を申告して登録できる。全員がランナーの一覧を見られる

**Independent Test**: 権限あり/なしの主体での作成、許可リスト内/外の申告での登録、トークンの返却、拒否の理由、監査ログを確認する(spec US1)

### Tests for User Story 1

- [X] T031 [P] [US1] 受け入れテストを `core/tests/acceptance/runner/test_us1_create_and_register.py` に作成する(US1-1〜US1-6、Edge Cases の「能力が空の申告」「未登録のランナー」「削除済みと同じ名前での作成」は US6 の後に T067 で追加。`ListRunners` にトークンが現れないこと = FR-027)
- [X] T032 [P] [US1] 同名の同時の作成の競合テストを `core/tests/acceptance/runner/test_concurrency_create.py` に作成する(一方だけが成立。data-model.md §8 の不変条件 4)

### Implementation for User Story 1

- [X] T033 [P] [US1] `CreateRunner` を `core/src/job_core/runner/application/commands/create.py` に実装する(contracts/application-api.md「CreateRunner」。ランナーとトークンを同じ UoW で作り、監査 `RUNNER_CREATE`・`TOKEN_ISSUE`)
- [X] T034 [P] [US1] `ReplaceCapabilityAllowlist` を `core/src/job_core/runner/application/commands/allowlist.py` に、`GetCapabilityAllowlist` を `core/src/job_core/runner/application/queries/get_allowlist.py` に実装する(監査 `ALLOWLIST_CHANGE`。既存のランナーの能力は変えない。research.md R12)
- [X] T035 [US1] `RegisterRunner` を `core/src/job_core/runner/application/commands/register.py` に実装する(contracts/application-api.md「RegisterRunner」。許可リストの検査 → `Runner.register` → 接続の記録(`OFFLINE → ONLINE` なら `RUNNER_ONLINE`)→ 監査 `RUNNER_REGISTER`(`had_live_lease` を含む)。拒否は `DENIED`(`invalid_declaration`)で、能力・`Runner.last_seen_at` を変えない)。T033・T034 に依存
- [X] T036 [P] [US1] `ListRunners` と出力の型 `RunnerView` を `core/src/job_core/runner/application/queries/list_runners.py` に、`GetRunner` を `core/src/job_core/runner/application/queries/get_runner.py` に実装する(contracts/application-api.md「ListRunners / GetRunner」。`state` は `state_at(now)`、`running_job_id` は 001 の `find_unfinished_by_runner`。削除済み・トークンの情報を含めない)。あわせて `GetRunnerHistory`(`core/src/job_core/runner/application/queries/get_runner_history.py`。ランナーごとの成功した操作の経緯を `job.general` で全員に返す。spec FR-029、001 FR-026 に倣う)と、`AuditRecordView.runner_id`・`GetAuditLog` の `runner_id` の条件を加える

**Checkpoint**: US1 の受け入れテストが通る。ランナーが作成・登録され、一覧で online と能力が見える

---

## Phase 4: User Story 2 - 要件を満たしうるランナーがいるかを判定する (Priority: P1)

**Goal**: 001 の提出時の判定を、002 の照合の規則で行う

**Independent Test**: 能力の異なるランナーを登録し、さまざまな要件で判定の結果と文法のエラーを確認する(spec US2)

### Tests for User Story 2

- [X] T037 [P] [US2] 受け入れテストを `core/tests/acceptance/runner/test_us2_eligibility.py` に作成する(US2-1〜US2-6。US2-5 は 001 の `SubmitJob` を通して `ValidationFailed("requirement", ...)` になること)
- [X] T038 [P] [US2] 001 の `RunnerEligibilityContract` を 002 の実装で実行する `testing/tests/test_runner_eligibility_service.py` を作成する(`requirement_for` は `{"all": [{"key", "op": "eq", "value"}...]}` を作る。contracts/ports.md)

### Implementation for User Story 2

- [X] T039 [US2] `RunnerEligibilityService` を `core/src/job_core/runner/application/eligibility.py` に実装する(contracts/application-api.md「001 への契約」。`RunnerCatalog` と T012 の `parse_requirement`・`satisfies` だけを使う。状態は見ない)
- [X] T040 [US2] 001 の `core/src/job_core/job/application/commands/_admission.py`(提出・やり直しの共通の判定)で、`RunnerEligibility` が送出した `InvalidRequirement` を `ValidationFailed("requirement", reason)` として拒否する(plan.md「001 への変更」4)。001 側は `job_core.runner` を import せず、`JobCoreError` の `code` で判別する(import-linter の `job-independent-of-runner`)

**Checkpoint**: US2 の受け入れテストと、002 の実装での 001 の契約テストが通る

---

## Phase 5: User Story 3 - 空いた online のランナーに、条件を満たすジョブだけを割り当てる (Priority: P1)

**Goal**: ランナーの要求に対し、状態を確認し、条件を満たす最前のジョブを割り当て、リースを同じ確定で作る

**Independent Test**: ランナーと待機列を用意し、割り当てられるジョブ(またはなし)とリースの期限を確認する(spec US3)

### Tests for User Story 3

- [X] T041 [P] [US3] 受け入れテストを `core/tests/acceptance/runner/test_us3_request_job.py` に作成する(US3-1〜US3-4。US3-4 は maintenance・機材の異常・offline のそれぞれで `NOT_ONLINE(state)`。maintenance・異常はテストの準備として Fake に直接設定してよい)
- [X] T042 [P] [US3] 同時実行のテストを `core/tests/acceptance/runner/test_concurrency_request_job.py` に作成する(US3-5: 2 台が同時に 1 件を求める → 一方だけ。maintenance の設定と割り当てが同時 → 割り当てはやり直して `NOT_ONLINE`。data-model.md §8 の不変条件 1・6。spec SC-002)
- [X] T043 [P] [US3] 判定と割り当ての一致の property-based テストを `core/tests/acceptance/runner/test_eligibility_consistency.py` に作成する(Hypothesis で生成した能力と要件で、`any_registered_runner_may_satisfy` が真 ⇔ online にしたそのランナーの `RequestJob` が割り当てる。spec SC-001、research.md R16)
- [X] T044 [P] [US3] 性能の目安のテストを `core/tests/perf/test_request_job_perf.py` に作成する(マーカー `perf`。待機中 500 件・ランナー 50 台で 50 ms 以下。research.md R11)

### Implementation for User Story 3

- [X] T045 [US3] 001 の `core/src/job_core/job/application/commands/assign.py` から、割り当ての本体を `assign_next_in(uow, deps, principal, runner_id, satisfies)` として切り出し、`AssignNextJob` はそれを呼ぶだけにする。`ASSIGN` の監査記録に任意の `runner_id`・`lease_id` を渡せるようにする(plan.md「001 への変更」1、research.md R4)。001 の受け入れテストを変更せずに通す
- [X] T046 [US3] `RequestJob` と出力の型 `JobRequestResult`・`Assignment` を `core/src/job_core/runner/application/commands/request_job.py` に実装する(contracts/application-api.md「RequestJob」。1 回の UoW で: `require_self` → ランナーの読み込み → `state_at` が `ONLINE` か → `Runner.last_seen_at` の更新 → `assign_next_in`(このランナーの `Runner.capabilities` で `satisfies`)→ `Lease.grant`(`RunnerTimingPolicy.lease_duration`)。衝突は 001 の `run_in_unit_of_work` でやり直す)。T045 に依存

**Checkpoint**: US3 の受け入れ・同時実行・一致・性能のテストが通る。**P1(US1〜US3)の完了で、ランナーを登録してジョブを割り当てる MVP が成り立つ**

---

## Phase 6: User Story 4 - 生存通知でランナーの状態とリースを保つ (Priority: P1)

**Goal**: 生存通知で online とリースを保ち、途絶で offline・リース切れになる

**Independent Test**: 手動で進める時計で、生存通知の有無に応じた状態とリースの期限を確認する(spec US4)

### Tests for User Story 4

- [X] T047 [P] [US4] 受け入れテストを `core/tests/acceptance/runner/test_us4_heartbeat_and_lease.py` に作成する(US4-1〜US4-5、Edge Cases の「時刻のずれ」(ランナーの時刻を受け取らない)と「生存通知の重複・遅延」。SC-004(offline と判定する時間 + 30 秒以内に、割り当ての側で offline として扱われる)、SC-005(間隔どおりの通知でリースが切れない。長時間のジョブを模して 1000 回の通知))
- [X] T048 [P] [US4] `SweepRunners` の冪等性と記録のテストを `core/tests/acceptance/runner/test_sweep.py` に作成する(offline の記録、期限切れのリースの `EXPIRED` と `LEASE_EXPIRED`、終了したジョブのリースの `ENDED`、2 回目は 0 件、`runner.sweep` を持たない主体は拒否)

### Implementation for User Story 4

- [X] T049 [US4] `Heartbeat` を `core/src/job_core/runner/application/commands/heartbeat.py` に実装する(出力の型 `HeartbeatResult` は T023 で定義済み。contracts/application-api.md「Heartbeat」。`Runner.touch` → 接続の記録 → 有効なリースの `extend`(期限後は延長せず `lease_expires_at = None`)→ ジョブが終了したリースは `end`。リースの延長は監査に残さない。research.md R7、R14)
- [X] T050 [US4] `SweepRunners` を `core/src/job_core/runner/application/commands/sweep.py` に実装する(contracts/application-api.md「SweepRunners」。research.md R8。ランナーごと・リースごとに UoW を分け、1 件の衝突が全体を止めないようにする)

**Checkpoint**: US4 の受け入れテストと、時刻を進めたシナリオが通る

---

## Phase 7: User Story 5 - 機材の異常を申告し、割り当てを自動で止める (Priority: P2)

**Goal**: ランナー経由の異常・回復の申告と、権限を持つ利用者の手動の解除

**Independent Test**: 異常と回復を申告し、状態・割り当ての停止と再開・監査ログを確認する(spec US5)

### Tests for User Story 5

- [X] T051 [P] [US5] 受け入れテストを `core/tests/acceptance/runner/test_us5_equipment_fault.py` に作成する(US5-1〜US5-5、Edge Cases の「異常の申告の重複」、SC-006(申告の受付後の割り当てが 0 件。T042 の同時実行のフックで申告と割り当てを競合させる))

### Implementation for User Story 5

- [X] T052 [P] [US5] `ReportFault`・`ReportRecovered` を `core/src/job_core/runner/application/commands/fault.py` に実装する(contracts/application-api.md。説明は data-model.md の `FaultDescription`、`Runner.fault`。`Runner.last_seen_at` も更新する。回復は異常があったときだけ `FAULT_RECOVERED`。research.md R13)
- [X] T053 [US5] `ClearFault` を同じ `core/src/job_core/runner/application/commands/fault.py` に追加する(`runner.manage`。異常がなければ記録せず変化なしで成功)。T052 に依存

**Checkpoint**: US5 の受け入れテストが通る

---

## Phase 8: User Story 6 - ランナーを無効化(maintenance)・削除する (Priority: P2)

**Goal**: maintenance で新しい割り当てを止めて戻せる。実行中のジョブがなければ削除できる

**Independent Test**: maintenance で割り当てが止まり、解除で再開し、削除後は判定・割り当ての対象から外れることを確認する(spec US6)

### Tests for User Story 6

- [X] T054 [P] [US6] 受け入れテストを `core/tests/acceptance/runner/test_us6_maintenance_and_delete.py` に作成する(US6-1〜US6-5。US6-3 は解除後に、異常と生存通知の状況で 3 通りになること。削除後に監査ログ(`GetAuditLog`)から削除したランナーの識別子と名前が分かること = FR-021。削除後に `AuthenticateRunner` が失敗し、`RunnerEligibilityService` の対象から外れること)

### Implementation for User Story 6

- [X] T055 [P] [US6] `SetMaintenance`・`ClearMaintenance` を `core/src/job_core/runner/application/commands/maintenance.py` に実装する(contracts/application-api.md。`Runner.maintenance`。実行中のジョブとリースは変えない)
- [X] T056 [P] [US6] `DeleteRunner` を `core/src/job_core/runner/application/commands/delete.py` に実装する(contracts/application-api.md「DeleteRunner」。判定の順序: 存在 → 権限 → 001 `find_unfinished_by_runner`。`Runner.deleted_at` の設定と有効なトークンの失効(`RunnerToken.revoked_at`)を同じ UoW で。`Runner.runner_id`・`Runner.name` は記録に残す = FR-021。監査 `RUNNER_DELETE` の `before` にランナーの名前を入れ、削除後も監査ログから識別子と名前を辿れるようにする。T054 にこの確認を含める)

**Checkpoint**: US6 の受け入れテストが通る

---

## Phase 9: User Story 7 - ランナーのトークンを発行・失効する (Priority: P2)

**Goal**: トークンの失効と再発行。値は発行時の 1 度だけ返り、どこにも現れない

**Independent Test**: 失効・再発行の後、旧トークンでの要求が拒否され、新トークンで受け付けられることを確認する(spec US7)

### Tests for User Story 7

- [X] T057 [P] [US7] 受け入れテストを `core/tests/acceptance/runner/test_us7_token.py` に作成する(US7-1〜US7-4。US7-4 は `Heartbeat`・`RegisterRunner`・`RequestJob`・異常の申告のすべてで `RunnerMismatch` と `DENIED`。トークンで認証した主体では、ランナーの作成・削除・maintenance・トークン操作・許可リストの変更とジョブの提出がすべて拒否されること = FR-025。再発行と認証の同時実行で、旧トークンが再発行の確定後に通らないこと)
- [X] T058 [P] [US7] トークンの非露出の property-based テストを `core/tests/acceptance/runner/test_token_non_exposure.py` に作成する(発行以外のすべてのユースケースの戻り値・監査記録・例外のメッセージを直列化し、発行したトークンの値とハッシュが現れないこと。spec SC-008、research.md R15-4)

### Implementation for User Story 7

- [X] T059 [US7] `ReissueToken`・`RevokeToken` を `core/src/job_core/runner/application/commands/token.py` に実装する(contracts/application-api.md。再発行は旧トークンの `RunnerToken.revoked_at` の設定と新トークンの発行を同じ UoW で。data-model.md §8 の不変条件 3)

**Checkpoint**: US7 の受け入れテストと非露出のテストが通る

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: 横断の検査、公開 API、試行の手段、文書の整合

- [X] T060 監査の網羅テストを `core/tests/acceptance/runner/test_audit_coverage.py` に作成する(spec FR-028・SC-010: 状態を変えるすべてのユースケース(T026、T033〜T035、T046、T049、T050、T052、T053、T055、T056、T059)の成功と拒否が、`runner_id` 付きで監査ログに記録され、001 の `GetAuditLog` で `runner_id` の条件で取り出せること。生存通知そのものは記録されないこと。閲覧範囲は 001 FR-026 に倣う(spec FR-029): `audit.read_all` を持たない主体には、`runner_id` で絞ったランナーごとの経緯のうち成功した記録だけが見え、拒否の記録(`DENIED`)は見えない。`audit.read_all` を持つ主体には拒否を含めてすべて見える。`runner.manage` だけの主体は拒否の記録を見られない。001 の閲覧範囲の判定がランナー系の記録(`job_id` なし)でも同じ規則になるよう、必要なら 001 の該当の問い合わせを最小限で直す)。T059 までのすべてに依存
- [X] T061 [P] 語彙・標準ライブラリのみ・禁止 API の検査が `job_core.runner` も対象にしていることを、`core/tests/architecture/test_imports.py`・`core/tests/architecture/test_vocabulary.py` で確認し、必要なら対象の列挙を直す(`secrets`・`hashlib`・`hmac`・`decimal` は許可。research.md R15。spec SC-012)
- [X] T062 ユースケース・問い合わせ・入出力の型・例外を `core/src/job_core/runner/application/__init__.py` から公開し、`__all__` を定める(contracts/application-api.md の名前と一致させる)
- [X] T063 [P] `testing/src/job_testing/core_fakes/__init__.py` の `build_core()` を拡張し、002 のユースケースを含め、既定の `RunnerEligibility` を 002 の `RunnerEligibilityService` に切り替えるオプションを加える(plan.md「001 への変更」5。001 のテストが使う `FakeRunnerEligibility` は残す)
- [X] T064 [P] quickstart.md §3 のシナリオ 1〜10 を通しで実行するテストを `core/tests/acceptance/runner/test_quickstart_walkthrough.py` に作成する(`build_core()` を使用)。あわせて spec SC-011 の最短経路(権限を持つ主体の作成 1 回 → 受け取ったトークンでの登録 → online になり割り当てを受ける。それ以外の手順を要しないこと)を検査する。PC へのトークンの設定・起動の手順は 004・009 で確認する。T063 に依存
- [X] T065 [P] `core/README.md` に runner コンテキストの節を追加する(責務、公開 API、ポートの一覧と実装の担当(core-persistence・003)、003・004・009 への引き継ぎ(plan.md「他の feature への引き継ぎ」)。contracts/ を参照し、内容を書き写さない)
- [X] T066 [P] 参照文書を 002 の決定に合わせる: `inputs/02-modules.md` の「コアが扱う汎用モデル」のランナー(状態に機材の異常を加え、能力は自己申告で値は 1 つの値か集合)と要件(比較の 5 種類)。`inputs/06-specify-004-runner-agent.md` の未確定事項のうち「機材故障の検知と、ランナーの状態への反映」に「002 で決定済み(ツール → エージェント → コアの申告)」と注記する
- [X] T067 [P] Edge Cases の残りの受け入れテストを `core/tests/acceptance/runner/test_edge_cases.py` に作成する(能力が空の申告、要件が空のジョブ、未登録のランナーの判定、再登録で要件を満たすランナーがいなくなっても待機中のジョブは残る、再登録で実行中のジョブを止めない、有効なリースを持つランナーの再登録で `had_live_lease = true`、削除済みと同じ名前での作成で別の識別子、削除後も監査ログから削除前のランナーの名前が分かる)
- [X] T068 `uv run ruff check`・`uv run mypy --strict core/src testing/src`・`Invoke-ScriptAnalyzer` の指摘を 0 件にする(quickstart.md V10、V11)
- [ ] T069 `.\ops\dev\setup-dev.ps1 -VerifyOnly` で quickstart.md の V1〜V18 をすべて通し、新しい環境での構築と再実行(冪等性)を確認する(quickstart.md §4、憲章 原則 14)。**実施状況**: 既存の環境での `-VerifyOnly` の V1〜V18 は 2026-11-21 にすべて成功。新しい Windows PC での構築と再実行の確認は未実施(002 は新しい依存・取得先を加えていないため、構築手順は 001 のまま)
- [X] T070 `docs/security/threat-model.md`(T001)の 002 の節の「対策」欄と §6「実装との対応」に、実装したタスクとテストの対応(T018・T026・T025・T052・T058 など)を追記する

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 依存なし。**T001(脅威モデルの追記)は実装の着手前の条件**(憲章 S6)。T002〜T004 は T001 の完了後
- **Foundational (Phase 2)**: Setup の完了が前提。すべてのユーザーストーリーをブロックする。T007 は 001 の監査の契約テストを変えるため、変更後に 001 のテスト全体を通すこと
- **US1 (Phase 3)**: Foundational が前提。他のストーリーに依存しない
- **US2 (Phase 4)**: Foundational と、テストでランナーを用意するために US1(T033〜T035)が前提
- **US3 (Phase 5)**: US1・US2(T039。判定と割り当ての一致のテスト T043 で使う)が前提
- **US4 (Phase 6)**: US1 と、リースを作るために US3(T046)が前提
- **US5 (Phase 7)**: US1 と US3(割り当ての停止の確認)が前提。US4・US6・US7 と並行できる
- **US6 (Phase 8)**: US1 と US3(実行中のジョブの準備)が前提。US5・US7 と並行できる
- **US7 (Phase 9)**: US1 が前提。T057 の US7-4 は US3・US4・US5 のユースケースを使うため、それらの後に完成させる
- **Polish (Phase 10)**: T060 は全コマンドの完了が前提。T061〜T063、T065、T066 は先に進めてよい

### User Story Dependencies(完了の順序)

```text
Setup(T001 脅威モデル) → Foundational
                             └─▶ US1 (P1) ─▶ US2 (P1) ─▶ US3 (P1) ─┬─▶ US4 (P1)
                                   │                                ├─▶ US5 (P2)
                                   │                                └─▶ US6 (P2)
                                   └─▶ US7 (P2)(T057 の一部は US3〜US5 の後)
                                                                         └─▶ Polish
```

### Within Each User Story

- テストを先に書き、失敗することを確かめる
- ドメイン(Phase 2 で完了済み)→ コマンド/問い合わせ → 監査の確認
- ストーリーの Checkpoint を満たしてから次の優先度へ

### Parallel Opportunities

- Setup: T001 の完了後、T003・T004 は並行可
- Foundational: T005・T006、T008・T009・T011・T015・T017・T019・T021(テスト)、T013・T014、T024・T027・T028 は並行可
- 各ストーリーのテスト(`[P]` 付き)は並行可
- US3 の完了後、US4・US5・US6 は並行できる。US7 は US1 の後に始められる

---

## Parallel Example: Foundational

```text
Task: "T008 値オブジェクトの単体テストを core/tests/unit/runner/test_values.py に作成"
Task: "T011 照合の単体テストを core/tests/unit/runner/test_matching.py に作成"
Task: "T015 Runner の単体テストを core/tests/unit/runner/test_runner.py に作成"
Task: "T017 CapabilityAllowlist の単体テストを core/tests/unit/runner/test_allowlist.py に作成"
Task: "T019 Lease の単体テストを core/tests/unit/runner/test_lease.py に作成"
Task: "T021 RunnerToken の単体テストを core/tests/unit/runner/test_token.py に作成"
```

## Parallel Example: User Story 3

```text
Task: "T041 受け入れテスト core/tests/acceptance/runner/test_us3_request_job.py"
Task: "T042 同時実行のテスト core/tests/acceptance/runner/test_concurrency_request_job.py"
Task: "T043 判定と割り当ての一致 core/tests/acceptance/runner/test_eligibility_consistency.py"
Task: "T044 性能の目安 core/tests/perf/test_request_job_perf.py"
```

## Parallel Example: US3 完了後

```text
Task: "T047 US4 の受け入れテスト core/tests/acceptance/runner/test_us4_heartbeat_and_lease.py"
Task: "T051 US5 の受け入れテスト core/tests/acceptance/runner/test_us5_equipment_fault.py"
Task: "T054 US6 の受け入れテスト core/tests/acceptance/runner/test_us6_maintenance_and_delete.py"
```

---

## Implementation Strategy

### MVP First(User Story 1〜3)

002 は 001 への契約(判定・割り当て)を提供する feature のため、US1 だけでは 001 から使えない。MVP は P1 のうち US1〜US3 とする。

1. Phase 1: Setup(**T001 脅威モデルの追記を先に完成**)
2. Phase 2: Foundational(すべてのストーリーをブロック)
3. Phase 3〜5: US1 → US2 → US3
4. **STOP and VALIDATE**: `uv run pytest core/tests/acceptance/runner core/tests/unit/runner` と、001 の全テスト、`uv run lint-imports` が通ることを確認

### Incremental Delivery

1. Setup + Foundational → 基盤が完成
2. US1〜US3 → 検証(MVP: ランナーを登録し、条件を満たすジョブを割り当てる)
3. US4 → 検証(生存通知とリース。004 の前提。P1 の完了)
4. US5、US6、US7 → 検証(運用操作)
5. Polish → `setup-dev.ps1 -VerifyOnly` で quickstart の全検証

### Parallel Team Strategy

1. 全員で Setup + Foundational
2. その後: A が US1 → US2 → US3 → US4、B が US1 の完了後に US7
3. US3 の完了後: A が US4、B が US5、C が US6
4. 最後に T060(監査の網羅)と Polish

---

## Notes

- `[P]` = 別のファイルで、未完了のタスクに依存しない
- `[USn]` = spec のユーザーストーリーへの対応
- 受け入れテストの名前に spec のシナリオ番号(`us3_5` など)を含め、spec との対応を追えるようにする
- フィールドの制約は data-model.md を正とし、タスクやコードのコメントに書き写さない
- 用途・プラットフォームの語を core に入れない(T061 が検出する)。テストの能力のキーは記号(`k1`、`set1`)を使う
- トークンの値をログ・例外・`repr` に出さない(T021、T058 が検出する)
- タスクまたは論理的なまとまりごとにコミットする

## Phase 11: Convergence

- [X] T071 `specs/001-core-job-queue/contracts/application-api.md`(権限の表を 12 種に、`GetAuditLog` に `runner_id` の条件、`AssignNextJob` の本体を `assign_next_in` として切り出したこと)と `specs/001-core-job-queue/data-model.md`(`AuditRecord.runner_id`、`AuditFilter.runner_id`、`AuditOperation` と `Denial.code` の追加)に、002 が加えた 001 への変更(plan: 001 への変更 1〜4)を追記し、001 の参照文書を実装と一致させる per plan: 001 への変更 / Constitution Governance(参照文書の食い違いの確認) (partial)
