---

description: "コア — ジョブの受付・キュー管理(001)の実装タスク"
---

# Tasks: コア — ジョブの受付・キュー管理

**Input**: `specs/001-core-job-queue/` の設計文書

**Prerequisites**: [plan.md](plan.md)、[spec.md](spec.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md)

**Tests**: 含める。憲章 原則 11(ドメイン層の単体テスト必須、状態遷移と権限の網羅、ポートの契約テスト)と、spec の SC-006・SC-007・SC-009・SC-010 がテストでの確認を求めているため。
各ストーリーでは、テストを先に書き、失敗することを確かめてから実装する。

**Organization**: ユーザーストーリーごとにフェーズを分け、ストーリー単位で実装・検証できるようにする。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並行して実施できる(別のファイルで、未完了のタスクに依存しない)
- **[Story]**: 対応するユーザーストーリー(US1〜US6)
- パスはリポジトリのルートからの相対パス([plan.md の Source Code](plan.md#source-code-repository-root) の構成に従う)
- フィールドの制約は [data-model.md](data-model.md) が正。タスクでは `data-model.md` の `Entity.field` を引用し、制約を書き写さない

---

## Phase 1: Setup(共通の基盤)

**Purpose**: 実装の前提条件(脅威モデル)と、プロジェクトの初期化

- [X] T001 脅威モデルを `docs/security/threat-model.md` に作成する(憲章 S6。**実装着手の前提条件**。plan.md Constitution Check の S6 ⚠️)。少なくとも core の信頼境界(呼び出し元が認証済みの `Principal` を渡す前提 = FR-024、権限の偽装、監査ログの改ざん・削除、ジョブ完了イベント経由の payload の漏洩 = FR-030、提出代行の名義の偽装、割り当て先でないランナーによる終了の報告・停止の確認の偽装)を、「誰を信頼するか・何から守るか・対策(本 feature のどのタスクで担保するか)・残るリスク」の形で記す。004/005 の範囲(作業フォルダ、ワークフロー)は節だけ設けて「各 feature の plan で追記」と記す
- [X] T002 uv ワークスペースのルート `pyproject.toml` を作成する(members: `core`、`testing`。開発時依存: pytest、hypothesis、pytest-cov、jsonschema、import-linter、ruff、mypy。`[tool.ruff]`、`[tool.mypy]`(strict)、`[tool.pytest.ini_options]`(マーカー `perf`、testpaths)を含む)。依存を解決した `uv.lock`(ハッシュ付き)をコミットする。research.md R1、R16、R17
- [X] T003 [P] `core/pyproject.toml`(配布名 `job-core`、import 名 `job_core`、`requires-python >=3.12`、**実行時の依存なし**、src レイアウト)と、空のパッケージ `core/src/job_core/{__init__,shared/__init__,access/__init__,job/__init__,job/domain/__init__,job/application/__init__,job/application/commands/__init__,job/application/queries/__init__}.py` を作成する。research.md R1
- [X] T004 [P] `testing/pyproject.toml`(配布名 `job-testing`、import 名 `job_testing`、依存 `job-core`)と、空のパッケージ `testing/src/job_testing/{__init__,core_fakes/__init__,contracts/__init__}.py`、`testing/tests/__init__.py` を作成する
- [X] T005 [P] 依存規則の契約 `.importlinter` を作成する(`job_core` は他の first-party を import しない forbidden 契約、`job_core.job.domain` → `job_core.job.application` の layers 契約、`job_core.access` は `job_core.job` を import しない)。research.md R15-1
- [X] T006 [P] 開発環境の設定ファイル `ops/dev/dev.config.psd1` を作成する(uv の版、配布元の URL(公式の配布元のみ)、SHA-256、Python の最低版 3.12、取得を許可するドメインの一覧(公式の配布元と PyPI のみ))。research.md R17、書き出し台帳 E15
- [X] T007 開発環境の構築スクリプト `ops/dev/setup-dev.ps1` を作成する(`[CmdletBinding(SupportsShouldProcess)]` による `-WhatIf`、事前確認(PowerShell 5.1 以上、Python 3.12 以上)、uv の取得(取得先が許可したドメインかを確認)と SHA-256 の検証(不一致なら停止して何も導入しない)、`uv sync --locked`(`uv.lock` のハッシュで検証)、2 回目は「変更なし」と表示する冪等性、`-VerifyOnly`(quickstart.md の V1〜V11 を順に実行して結果の一覧を表示)、`-Uninstall`(`.venv` とキャッシュを削除))。秘密情報は扱わない。T006 に依存。research.md R17、quickstart.md §2
- [X] T008 [P] `ops/dev/setup-dev.ps1` の Pester テスト `ops/dev/tests/setup-dev.Tests.ps1` を作成する(ドライランで変更しないこと、冪等性、ハッシュ不一致で停止すること、撤去)。T007 と並行して先に書いてよい

**Checkpoint**: 脅威モデルがあり、`ops/dev/setup-dev.ps1` で空の core パッケージのテスト環境が構築できる

---

## Phase 2: Foundational(全ストーリーの前提)

**Purpose**: 値オブジェクト・集約・ポート・権限の判定・Fake・契約テスト・アーキテクチャの検査

**⚠️ CRITICAL**: このフェーズが終わるまで、ユーザーストーリーの作業を始めない

### 共有部品と access コンテキスト

- [X] T009 [P] 識別子の型を `core/src/job_core/shared/ids.py` に実装する(data-model.md の `JobId`、`RunnerId`、`SubjectId`)
- [X] T010 [P] 例外の基底 `JobCoreError`(機械可読の `code` と追加情報を持つ)を `core/src/job_core/shared/errors.py` に実装する。contracts/application-api.md「拒否の一覧」
- [X] T011 [P] ポート `Clock`・`IdGenerator` を `core/src/job_core/shared/ports.py`、ドメインイベントの基底を `core/src/job_core/shared/events.py` に実装する。contracts/ports.md「Clock / IdGenerator」、research.md R14
- [X] T012 [P] `Permission`(9 種と値。spec FR-023 の 7 種 + `job.execute`・`retention.purge`)を `core/src/job_core/access/permission.py`、`Principal`・`PrincipalKind` を `core/src/job_core/access/principal.py` に実装する(data-model.md の `Principal.subject_id`、`Principal.permissions`、`Principal.kind`。contracts/application-api.md「権限」)

### job ドメイン(テスト → 実装)

- [X] T013 [P] 値オブジェクトの単体テストを `core/tests/unit/job/test_values.py` に作成する(各値の境界値。data-model.md §1 の表のすべての行)
- [X] T014 [P] ドメインの例外(contracts/application-api.md「拒否の一覧」の `ValidationFailed` 〜 `RunnerMismatch`。`ConcurrencyConflict` を含む)を `core/src/job_core/job/domain/errors.py` に実装する。T010 に依存
- [X] T015 値オブジェクトを `core/src/job_core/job/domain/values.py` に実装する(data-model.md の `JobType`、`RunnerRequirement`、`Payload`、`Timeout`、`SourceRef.source`、`SourceRef.revision`、`ResultSummary`、`Reason`、`Placement.anchor`、`Placement.side`、`DuplicateKey`)。`Payload` は深いコピーで不変にする(research.md R12)。違反は `ValidationFailed(field, detail)`。T013 を通す
- [X] T016 `JobDefinition`(`duplicate_key()` を含む)と `Submitter` を `core/src/job_core/job/domain/definition.py` に実装する(data-model.md の `JobDefinition.job_type`、`JobDefinition.requirement`、`JobDefinition.payload`、`JobDefinition.timeout`、`JobDefinition.source_ref`、`Submitter.owner`、`Submitter.submitted_by`)。必須の欠落は `ValidationFailed`(FR-003)。T015 に依存
- [X] T017 [P] ジョブ完了イベント `JobCompleted` を `core/src/job_core/job/domain/events.py` に実装する(data-model.md の `JobCompleted.event_id`、`JobCompleted.event_type`、`JobCompleted.schema_version`、`JobCompleted.occurred_at`、`JobCompleted.job_id`、`JobCompleted.state`、`JobCompleted.finished_at`、`JobCompleted.retry_of`、`JobCompleted.submitter_id`)。payload・要約・ランナーの項目を持たない(FR-030)。T011 に依存
- [X] T018 [P] 状態遷移の単体テストを `core/tests/unit/job/test_job_transitions.py` に作成する(data-model.md「JobState と遷移表」の全行を表駆動で。終了状態からの全操作が `InvalidStateTransition`、`request_abort` の二重要求が `AbortAlreadyRequested`、要求後に `finish` すると `superseded_by` が設定されること、割り当て先でないランナーの `finish`・`confirm_stopped` が `RunnerMismatch` で状態を変えないこと、終了の遷移で `JobCompleted` が 1 件積まれること)
- [X] T019 `Job` 集約・`JobState`・`CancellationRecord` を `core/src/job_core/job/domain/job.py` に実装する(data-model.md の `Job.job_id`、`Job.definition`、`Job.submitter`、`Job.submitted_at`、`Job.state`、`Job.assigned_runner_id`、`Job.started_at`、`Job.finished_at`、`Job.result_summary`、`Job.cancellation`、`Job.retry_of`、`Job.version`、`CancellationRecord.kind`、`CancellationRecord.requested_by`、`CancellationRecord.requested_at`、`CancellationRecord.reason`、`CancellationRecord.confirmed_at`、`CancellationRecord.superseded_by`)。メソッドは遷移表の `assign`・`cancel_queued`・`request_abort`・`confirm_stopped`・`finish`(後の 2 つは報告したランナーの `runner_id` を受け取り、`Job.assigned_runner_id` と一致しなければ `RunnerMismatch`)。積んだイベントの取り出し `pull_events()` を持つ。T016、T017 に依存し、T018 を通す
- [X] T020 [P] 待機列の単体テストを `core/tests/unit/job/test_queue.py` に作成する(data-model.md §3 の操作と拒否の条件、位置が変わらない移動の無変化、空の待機列への位置指定。Hypothesis で「重複なし」「移したジョブ以外の相対順序は不変」「操作列の後も `position_of` が一貫」を検査)
- [X] T021 `Queue` 集約を `core/src/job_core/job/domain/queue.py` に実装する(data-model.md の `Queue.queue_id`、`Queue.entries`、`Queue.version`。操作 `append`・`insert`・`move`・`remove`・`position_of`・`first_matching`)。T014、T015 に依存し、T020 を通す
- [X] T022 [P] 監査ログの記録 `AuditRecord`・`AuditOperation`・`AuditOutcome` を `core/src/job_core/job/domain/audit.py` に実装する(data-model.md の `AuditRecord.record_id`、`AuditRecord.occurred_at`、`AuditRecord.actor`、`AuditRecord.actor_kind`、`AuditRecord.on_behalf_of`、`AuditRecord.operation`、`AuditRecord.job_id`、`AuditRecord.before`、`AuditRecord.after`、`AuditRecord.reason`、`AuditRecord.outcome`、`AuditRecord.denial`)。`before`/`after` の項目は data-model.md §4 の操作ごとの表に従い、payload を入れない。T012 に依存

### application の基盤

- [X] T023 ポート(`UnitOfWork`、`JobRepository`、`QueueRepository`、`AuditLog`、`Outbox`、`RunnerEligibility`)と `OutboxEntry` を `core/src/job_core/job/application/ports.py` に `typing.Protocol` で定義する(contracts/ports.md の各シグネチャと約束。data-model.md の `OutboxEntry.event`、`OutboxEntry.status`、`OutboxEntry.recorded_at`、`OutboxEntry.dispatched_at`、`OutboxEntry.attempts`)。T019、T021、T022 に依存
- [X] T024 [P] 権限の判定の網羅テストを `core/tests/unit/test_authorization.py` に作成する(9 権限の全部分集合 512 通り × 所有(自分/他人)× 対象の状態 × 操作。期待値は contracts/application-api.md「可否の表」。`Principal.kind` を変えても結果が変わらないこと(憲章 原則 9)も検査する。SC-006)
- [X] T025 可否の純粋な関数(`authorize_submit`、`authorize_retry`、`authorize_reschedule`、`authorize_cancel`、`authorize_view`、`authorize_audit_read_all`、`authorize_execute`、`authorize_purge`)を `core/src/job_core/job/application/authorization.py` に実装する。拒否は `PermissionDenied(required=[...])`。判定には `Principal.permissions` だけを使い、`Principal.kind` を参照しない。research.md R8 の「判断が必要だった点」1〜5 に従う。T012、T014 に依存し、T024 を通す
- [X] T026 楽観的排他の衝突時に判定からやり直す `run_in_unit_of_work`(既定 3 回、使い切ったら `ConcurrencyConflict`)を `core/src/job_core/job/application/retry_policy.py` に実装する。research.md R4、contracts/application-api.md「共通の約束」。T023 に依存
- [X] T027 [P] 監査記録の組み立てと、権限による拒否(`PermissionDenied`)と割り当て先でないランナーからの報告(`RunnerMismatch`)を別の UoW で `AuditLog.append_denied` に記録する補助を `core/src/job_core/job/application/audit_support.py` に実装する(research.md R9)。T022、T023 に依存

### Fake と契約テスト

- [X] T028 [P] 固定・手動で進められる時計 `FakeClock` と連番の `SequentialIdGenerator` を `testing/src/job_testing/core_fakes/clock_ids.py` に実装する。T011 に依存
- [X] T029 メモリ上の `InMemoryUnitOfWork`・`InMemoryJobRepository`・`InMemoryQueueRepository`・`InMemoryAuditLog`・`InMemoryOutbox` を `testing/src/job_testing/core_fakes/repositories.py` に実装する(contracts/ports.md の約束 1〜5。コミット時の `version` 比較、集約のイベントをアウトボックスへ書き込む、`append_denied` の独立した確定、テスト用の「コミット直前に別の操作を割り込ませる」フック)。T023 に依存
- [X] T030 [P] `FakeRunnerEligibility`(ランナーの識別子 → 能力の集合 の表。要件 = 能力の部分集合で照合。登録・登録解除の操作)を `testing/src/job_testing/core_fakes/runners.py` に実装する。contracts/ports.md「RunnerEligibility」。T023 に依存
- [X] T031 [P] 契約テスト群 `UnitOfWorkContract`・`JobRepositoryContract`・`QueueRepositoryContract`・`QueueJobConsistency` を `testing/src/job_testing/contracts/persistence.py` に作成する(contracts/ports.md「契約テストの一覧」。実装を受け取るフィクスチャで抽象化し、core-persistence からも再利用できる形にする)。T023 に依存
- [X] T032 [P] 契約テスト群 `AuditLogContract`・`OutboxContract` を `testing/src/job_testing/contracts/audit_outbox.py` に作成する。T023 に依存
- [X] T033 [P] 契約テスト群 `RunnerEligibilityContract` を `testing/src/job_testing/contracts/runner_eligibility.py` に作成する(002 の実装も同じテストを通す)。T023 に依存
- [X] T034 契約テストを Fake に対して実行する `testing/tests/test_fake_contracts.py` を作成し、全件を通す(quickstart.md V4)。T029〜T033 に依存
- [X] T035 受け入れテスト用の共通フィクスチャ(Fake の組み立て、権限の組み合わせを持つ `Principal` の生成、ジョブ定義の生成)を `core/tests/acceptance/conftest.py` に作成する。T028〜T030 に依存

### アーキテクチャの検査(最初から CI で守る)

- [X] T036 [P] 標準ライブラリのみ・禁止 API の検査を `core/tests/architecture/test_imports.py` に作成する(AST で `job_core` の全 import を列挙し、`sys.stdlib_module_names` と `job_core` 以外を検出、`socket`・`http`・`urllib`・`ssl`・`smtplib`・`subprocess`・`ftplib` 等を禁止。FR-028、FR-029。research.md R15-2、R15-3)
- [X] T037 [P] 語彙検査を `core/tests/architecture/test_vocabulary.py` に、禁止語の一覧を `core/tests/architecture/forbidden_terms.txt` に作成する(プラットフォーム名・CI 製品名・用途固有の語。大文字小文字を区別せず、識別子・文字列・コメントを対象。SC-009。research.md R15-4)。一覧の語は検査対象のソースの外(このテキストファイル)だけに置く

**Checkpoint**: ドメインの単体テスト・権限の網羅テスト・Fake の契約テスト・アーキテクチャの検査がすべて通る。ユーザーストーリーに着手できる

---

## Phase 3: User Story 1 - ジョブを提出し、並んだ順に実行される (Priority: P1) 🎯 MVP

**Goal**: ジョブ追加の権限を持つ主体がジョブを提出でき、末尾に並び、条件を満たすランナーに前から順に 1 件ずつ割り当てられる

**Independent Test**: Fake のランナー一覧を用意して複数のジョブを提出し、受付/拒否の結果と、ランナーが空くたびに割り当てられるジョブの順序を確認する(spec US1)

### Tests for User Story 1

- [X] T038 [P] [US1] 受け入れテスト `core/tests/acceptance/test_us1_submit_and_order.py` を作成する(US1-1〜US1-7 をテスト名 `test_us1_1_...` の形で 1 対 1 に。加えて spec Edge Cases: 必須項目の欠落・タイムアウトが正でない、提出者が違っても同じ内容は重複、出所情報のないジョブは重複判定しない、受付後に全ランナーが登録解除されても待機のまま、提出代行の権限のない代理提出の拒否、提出代行で `Submitter.owner` と `Submitter.submitted_by` が両方記録されること、権限による拒否が `DENIED` として記録されること、割り当て先でないランナーからの終了の報告が `RunnerMismatch` で拒否され、ジョブが実行中のまま `DENIED` が記録されること、`job.execute` のない主体の割り当て・終了の報告が主体の種類によらず `PermissionDenied` になること、同じ提出者が多数(例: 600 件)のジョブを待機させられること(FR-007)、存在しないジョブの終了の報告が `JobNotFound` になること)
- [X] T039 [P] [US1] 同時の提出の競合テスト `core/tests/acceptance/test_concurrency_submit.py` を作成する(同じ内容の 2 件の同時提出で、一方だけが受け付けられ他方が `DuplicateQueuedJob`。Fake のコミット直前のフックを使う。割り当てと提出の同時実行で待機列の不変条件が保たれること)

### Implementation for User Story 1

- [X] T040 [US1] 受付の判定(定義の検証、`RunnerEligibility.any_registered_runner_may_satisfy`、待機中の重複の照合、待機列への追加と位置の算出)を `core/src/job_core/job/application/commands/_admission.py` に実装する。US2・US4 から再利用する。判定の順序は contracts/application-api.md「共通の約束」の提出の順。FR-002、FR-006
- [X] T041 [US1] `SubmitJob`(末尾への追加と提出代行。位置の指定 `placement` は本ストーリーでは扱わず、T047 で追加する)を `core/src/job_core/job/application/commands/submit.py` に実装する。出力 `SubmitResult(job_id, position)`、監査 `SUBMIT`。contracts/application-api.md「SubmitJob」。T040 に依存
- [X] T042 [US1] `AssignNextJob`(`authorize_execute` で `job.execute` を判定、ランナーに未終了のジョブがあれば `RunnerBusy`、待機列を先頭から走査して `runner_satisfies` が真の最初のジョブを取り出し `assign`、監査 `ASSIGN`)を `core/src/job_core/job/application/commands/assign.py` に実装する。research.md R6、FR-009、FR-010
- [X] T043 [US1] `ReportFinished`(入力に報告するランナーの `runner_id` を持つ。`authorize_execute` で `job.execute` を判定、割り当て先でなければ `RunnerMismatch` を `DENIED` として記録して拒否、`finish` を呼び、監査 `COMPLETE`、アウトボックスに `JobCompleted`。出力 `FinishResult`)を `core/src/job_core/job/application/commands/report_finished.py` に実装する。`result_summary` は data-model.md の `ResultSummary` に従う。contracts/application-api.md「ReportFinished」
- [X] T044 [P] [US1] 性能の目安のテストを `core/tests/perf/test_submit_perf.py` に作成する(マーカー `perf`。待機中 500 件・ランナー 50 台の Fake で提出の判定が 50 ms 以下。quickstart.md V9、SC-005)

**Checkpoint**: US1 の受け入れテストと競合テストが通る。待機列に並べて順番に実行する最小の価値が成立(MVP)

---

## Phase 4: User Story 2 - 権限を持つ利用者が、位置を指定して追加し、スケジュールを変更する (Priority: P1)

**Goal**: スケジュール変更の権限を持つ利用者が、指定した待機中のジョブの前後へのジョブの追加と、待機中のジョブの移動を、実行中のジョブを止めずに行える

**Independent Test**: 複数の提出者のジョブを待機させ、前後への追加と他人のジョブの移動で並びと次の割り当てが変わること、実行中のジョブが影響を受けないこと、権限のない操作が拒否されることを確認する(spec US2)

### Tests for User Story 2

- [X] T045 [P] [US2] 受け入れテスト `core/tests/acceptance/test_us2_placement_and_reschedule.py` を作成する(US2-1〜US2-7。加えて spec Edge Cases: 基準が待機中でない位置指定の提出は末尾に切り替えずに拒否、待機列が空での位置指定の拒否、自分自身の前後への移動の拒否、位置が変わらない移動は成功で無変化、同じジョブの連続した移動は後が有効で両方が監査に残る、移動の監査に前後の位置が残る、実行中のジョブの状態が変わらないこと(FR-013、SC-003)、相談の結果を待機中のジョブ 1 件につき 1 回の `RescheduleJob` で反映できること(SC-004)、存在しないジョブの移動が `JobNotFound` になること)
- [X] T046 [P] [US2] 移動と割り当ての競合テスト `core/tests/acceptance/test_concurrency_reschedule.py` を作成する(移すジョブまたは基準のジョブが先に割り当てられたら、移動は `TargetNotQueued` / `AnchorNotQueued` で拒否され、待機列は割り当ての結果のまま)

### Implementation for User Story 2

- [X] T047 [US2] `SubmitJob` に位置の指定を実装する(`QUEUE_SCHEDULE` の判定、`Queue.insert`、基準が待機中でなければ `AnchorNotQueued` でジョブを作らない、監査 `SUBMIT_PLACED` に `anchor`・`side`)を `core/src/job_core/job/application/commands/submit.py` と `core/src/job_core/job/application/commands/_admission.py` に追加する。data-model.md の `Placement.anchor`、`Placement.side`。FR-004a
- [X] T048 [US2] `RescheduleJob`(`Queue.move`、出力 `RescheduleResult(job_id, position_before, position_after)`、監査 `RESCHEDULE`)を `core/src/job_core/job/application/commands/reschedule.py` に実装する。contracts/application-api.md「RescheduleJob」、FR-011、FR-012

**Checkpoint**: US1 と US2 の受け入れテストがともに通る。運用中に順序を制御できる(本 feature の存在理由)

---

## Phase 5: User Story 3 - 待機中のジョブを取り消し、実行中のジョブを強制中断する (Priority: P2)

**Goal**: 自分のジョブの中断と、取り消し・強制中断の権限による他人のジョブの中断を、理由とともに記録して行える

**Independent Test**: 待機中のジョブの取り消しと実行中のジョブの強制中断を行い、状態・理由・中断者が記録されること、権限のない中断が拒否されることを確認する(spec US3)

### Tests for User Story 3

- [X] T049 [P] [US3] 受け入れテスト `core/tests/acceptance/test_us3_cancel_and_abort.py` を作成する(US3-1〜US3-6。加えて: 強制中断の理由の欠落で `ReasonRequired`、二重の強制中断で `AbortAlreadyRequested`、中断の要求後に先に成功/失敗が報告されたら終了を正とし `CancellationRecord.superseded_by` が記録されること、提出代行のジョブは名義上の提出者が「自分のジョブ」として中断できること、取り消し後に後ろのジョブが前に詰まること、中断の確定でアウトボックスに `JobCompleted` が 1 件、割り当て先でないランナーからの停止の確認が `RunnerMismatch` で拒否されること、存在しないジョブの中断・停止の確認が `JobNotFound` になること)
- [X] T050 [P] [US3] 取り消しと割り当ての競合テスト `core/tests/acceptance/test_concurrency_cancel.py` を作成する(取り消しが先なら割り当てられない。割り当てが先なら実行中として判定し直され、取り消しの権限だけを持つ利用者の他人のジョブへの操作は `PermissionDenied`、本人の操作は強制中断の要求になる)

### Implementation for User Story 3

- [X] T051 [US3] `CancelJob`(その時点の状態と所有で `authorize_cancel`、待機中は `cancel_queued` と `Queue.remove`・監査 `CANCEL_QUEUED`、実行中は `request_abort`・監査 `ABORT_REQUEST`、出力 `CancelResult(job_id, state, abort_pending)`)を `core/src/job_core/job/application/commands/cancel.py` に実装する。理由は data-model.md の `CancellationRecord.reason` に従う。FR-014〜FR-016
- [X] T052 [US3] `ConfirmStopped`(入力に停止を確認したランナーの `runner_id` を持つ。`authorize_execute` で `job.execute` を判定、割り当て先でなければ `RunnerMismatch` を `DENIED` として記録して拒否、`confirm_stopped`、監査 `ABORT_CONFIRM`、アウトボックスに `JobCompleted`)を `core/src/job_core/job/application/commands/confirm_stopped.py` に実装する。contracts/application-api.md「ConfirmStopped」
- [X] T053 [US3] `ReportFinished` の出力 `superseded_abort` と、監査 `COMPLETE` の `after.superseded_abort` を、中断の要求があった場合に設定するよう `core/src/job_core/job/application/commands/report_finished.py` を更新する(spec Edge Cases「強制中断の要求のあと…先に確定した終了を正とする」)

**Checkpoint**: US1〜US3 の受け入れテストが通る

---

## Phase 6: User Story 4 - 終了したジョブをやり直す (Priority: P2)

**Goal**: ジョブ追加の権限を持つ主体が、誰の終了したジョブでも、同じ定義で新しいジョブとしてやり直せ、元のジョブとの関連を辿れる

**Independent Test**: 終了したジョブをやり直し、同じ定義の新しいジョブが末尾に入ること、新旧の関連がどちらからも辿れること、元のジョブが変わらないことを確認する(spec US4)

### Tests for User Story 4

- [X] T054 [P] [US4] 受け入れテスト `core/tests/acceptance/test_us4_retry.py` を作成する(US4-1〜US4-7。新旧の関連は `JobRepository.find_retries_of` と `Job.retry_of` で確認する。加えて spec Edge Cases: やり直しのやり直しで関連を辿って最初のジョブまで遡れる、同じ内容が待機中ならやり直しも `DuplicateQueuedJob`、元のジョブの定義(出所のリビジョンを含む)が同一の値で引き継がれる、元のジョブの `Job.version` と全項目が変わらない)

### Implementation for User Story 4

- [X] T055 [US4] `RetryJob`(`authorize_retry`、元のジョブが終了状態でなければ `InvalidStateTransition`、元の `JobDefinition` をそのまま使い `Submitter.owner`・`Submitter.submitted_by` = やり直した主体、`Job.retry_of` = 元のジョブ、受付の判定は `_admission.py` を再利用、位置の指定は US2 と同じ規則、監査 `RETRY`)を `core/src/job_core/job/application/commands/retry.py` に実装する。contracts/application-api.md「RetryJob」、FR-017〜FR-020。位置の指定のテスト(US4-6)は T047 の完了が前提

**Checkpoint**: US1〜US4 の受け入れテストが通る

---

## Phase 7: User Story 5 - ジョブの状態と結果を確認する (Priority: P2)

**Goal**: すべての利用者が、全員のジョブの状態・結果・待機列の位置を、待機列の並び順で確認できる

**Independent Test**: 複数の提出者のジョブを用意し、一般の提出者にも全件が同じ項目で、待機列の並び順どおりに見えることを確認する(spec US5)

### Tests for User Story 5

- [X] T056 [P] [US5] 受け入れテスト `core/tests/acceptance/test_us5_views.py` を作成する(US5-1〜US5-3。加えて: 一覧に payload が含まれず詳細には含まれる、詳細の `retry_of` と `retries` で新旧を辿れる、存在しないジョブは `JobNotFound`、`GENERAL` のない主体は `PermissionDenied`、終了済みの頁送り)

### Implementation for User Story 5

- [X] T057 [P] [US5] 表示用の型 `JobSummaryView`・`JobDetailView`・`RelatedJobRef`・`JobListView` を `core/src/job_core/job/application/queries/job_views.py` に実装する(contracts/application-api.md「ListJobs」「GetJob」の項目)
- [X] T058 [US5] `ListJobs`(待機中は待機列の並び順で位置付き、実行中は全件、終了済みは `Job.finished_at` の新しい順で頁送り、既定 100)を `core/src/job_core/job/application/queries/list_jobs.py` に実装する。T057 に依存。FR-022
- [X] T059 [US5] `GetJob`(定義・中断の記録・`RelatedJobRef(job_id, exists)`・`retries`)を `core/src/job_core/job/application/queries/get_job.py` に実装する。T057 に依存

**Checkpoint**: US1〜US5 の受け入れテストが通る

---

## Phase 8: User Story 6 - 状態変更の記録と完了の知らせ(監査ログ・完了イベント)(Priority: P3)

**Goal**: 状態を変える操作の経緯を全員が確認でき、監査ログ全体は管理者が閲覧でき、ジョブの終了が取りこぼしなくイベントとして発行される。記録とジョブは保持期間で自動削除される

**Independent Test**: 各操作の監査ログを確認し、イベントの受け手を一時的に止めて終了させ、復旧後にイベントが届くことを確認する(spec US6)

### Tests for User Story 6

- [X] T060 [P] [US6] 受け入れテスト `core/tests/acceptance/test_us6_audit_and_history.py` を作成する(US6-1〜US6-4。加えて SC-007: すべての状態を変える操作(data-model.md §4 の `AuditOperation` の各値)について、成功時に 1 件の記録があり、`AuditRecord.before`・`AuditRecord.after` が表のとおりであることを表駆動で検査。監査ログ全体の閲覧の拒否も記録されること)
- [X] T061 [P] [US6] 受け入れテスト `core/tests/acceptance/test_us6_completion_events.py` を作成する(US6-5、US6-6: 成功/失敗/中断の各終了で `JobCompleted` が 1 件 `PENDING` になる、`mark_dispatched` までは再取得で同じ `event_id` が返る、終了状態はイベントの未配信と無関係に確定している。SC-008)
- [X] T062 [P] [US6] イベントの契約テスト `core/tests/contract/test_job_completed_event.py` を作成する(直列化の結果が JSON Schema に適合する。Hypothesis で任意の payload・結果の要約を持つジョブを終了させ、その値が直列化の結果に文字列としても現れないこと。SC-010)
- [X] T063 [P] [US6] 保持期間のテスト `core/tests/acceptance/test_retention.py` を作成する(FR-031、FR-032: 期間を過ぎた終了済みのジョブと監査記録だけが消え、待機中・実行中は消えない、`audit_retention < job_retention` は設定エラー、元のジョブが削除されたやり直しのジョブは残り `RelatedJobRef.exists = false`、削除済みのジョブのやり直しは `JobNotFound`、削除後も監査ログが残っていれば操作の経緯を返す、`PURGE` の記録が 1 件)

### Implementation for User Story 6

- [X] T064 [P] [US6] ジョブ完了イベントの JSON Schema を、パッケージ内の `core/src/job_core/job/schemas/job_completed.v1.json` に配置する(内容は [contracts/job-completed-event.schema.json](contracts/job-completed-event.schema.json) と同一。両者が一致することを T062 で検査する)
- [X] T065 [US6] `JobCompleted.to_dict()`(状態は小文字、日時は ISO 8601 の UTC)を `core/src/job_core/job/domain/events.py` に追加する。T062 を通す
- [X] T066 [P] [US6] 表示用の型 `AuditRecordView` を `core/src/job_core/job/application/queries/audit_views.py` に実装する(data-model.md の `AuditRecord` の全項目から、payload を含まない形で)
- [X] T067 [US6] `GetJobHistory`(`AuditLog.history_of`。`DENIED` を含まない。削除済みのジョブでも記録を返す)を `core/src/job_core/job/application/queries/get_job_history.py` に実装する。T066 に依存。FR-026
- [X] T068 [US6] `GetAuditLog`(`AUDIT_READ_ALL`、絞り込みと頁送り、拒否も `append_denied` で記録)を `core/src/job_core/job/application/queries/get_audit_log.py` に実装する。T066 に依存。FR-026
- [X] T069 [P] [US6] `RetentionPolicy` を `core/src/job_core/job/domain/retention.py` に実装する(data-model.md の `RetentionPolicy.job_retention`、`RetentionPolicy.audit_retention`)
- [X] T070 [US6] `PurgeExpired`(`authorize_purge` で `retention.purge` を判定、`Clock.now()` から期限を算出、`JobRepository.delete_finished_before` と `AuditLog.delete_before`、監査 `PURGE`、出力 `PurgeResult`)を `core/src/job_core/job/application/commands/purge.py` に実装する。T069 に依存。research.md R13

**Checkpoint**: US1〜US6 の受け入れテスト・契約テストがすべて通る

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 公開 API の整理、試行の手段、CI、文書の整合

- [X] T071 ユースケースと問い合わせ・入出力の型・例外を `core/src/job_core/job/application/__init__.py` から公開し、`__all__` を定める(contracts/application-api.md の名前と一致させる)
- [X] T072 [P] Fake をつないだユースケースの集合を返す `build_core()` を `testing/src/job_testing/core_fakes/__init__.py` に実装する(quickstart.md §4 の手で確かめるシナリオ用)
- [X] T073 [P] quickstart.md §4 のシナリオ 1〜11 を通しで実行するテストを `core/tests/acceptance/test_quickstart_walkthrough.py` に作成する(`build_core()` を使用)。T072 に依存
- [X] T074 [P] CI のワークフロー `.github/workflows/core-ci.yml` を作成する(Git のリポジトリのルートが server-sample の親のため、実際の配置は `../.github/workflows/server-sample-core-ci.yml`。Windows ランナー、`permissions: contents: read` のみ、Secrets 不使用、環境変数・ファイル一覧を出力しない。外への通信は書き出し台帳 E15 の取得のみ(公式の配布元と PyPI)。手順: `uv sync --locked`、`uv run pytest`(perf を除く)、`uv run lint-imports`、`uv run ruff check`、`uv run mypy --strict core/src testing/src`、`Invoke-Pester ops/dev/tests`、`Invoke-ScriptAnalyzer -Path ops/dev -Recurse`)。憲章 S4、原則 1
- [X] T075 [P] core パッケージの説明 `core/README.md` を作成する(責務、公開 API、ポートの一覧と実装の担当(002・core-persistence・003)、作らないもの。contracts/ を参照し、内容を書き写さない)
- [X] T076 `uv run ruff check`・`uv run mypy --strict core/src testing/src`・`Invoke-ScriptAnalyzer` の指摘を 0 件にする(quickstart.md V10、V11)
- [X] T077 `.\ops\dev\setup-dev.ps1 -VerifyOnly` で quickstart.md の V1〜V11 をすべて通し、新しい環境での構築と再実行(冪等性)を確認する(quickstart.md §5、憲章 原則 14)
- [X] T078 [P] 参照文書を憲章 v2.0.0(原則 5: 優先度の廃止)に合わせる(plan.md「追補」1〜4、research.md R18): `inputs/01-constitution.md` の原則 5 の入力の文言、`inputs/02-modules.md` の core の責務の「優先度」と汎用モデルの `priority`、`inputs/12-plan.md` のテストの「優先度」→「並び順」、`inputs/13-security-egress.md` E1 の「希望優先度」の削除。憲章自体の改定は完了済みのため対象外。本 feature の設計・実装はこの修正を前提としない
- [X] T079 `docs/security/threat-model.md`(T001)の「対策」欄に、実装したタスクとテストの対応(T025・T036・T037・T062 など)を追記する

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 依存なし。**T001(脅威モデル)は実装の着手前の条件**(憲章 S6)。T002〜T008(外部からの取得を含む構築スクリプトを含む)も実装に当たるため、**T001 の完了後**に始める
- **Foundational (Phase 2)**: Setup の完了が前提。すべてのユーザーストーリーをブロックする
- **US1 (Phase 3)**: Foundational の完了が前提。他のストーリーに依存しない
- **US2 (Phase 4)**: Foundational と、T040・T041(`_admission.py`・`submit.py`。同じファイルを拡張するため)が前提
- **US3 (Phase 5)**: Foundational が前提。テストで実行中のジョブを作るために T042(`AssignNextJob`)を使う。T053 は T043 の後
- **US4 (Phase 6)**: Foundational と T040 が前提。位置を指定したやり直し(US4-6)は T047 が前提
- **US5 (Phase 7)**: Foundational が前提(テストのデータは Fake に直接作ってよい)。US1〜US4 と並行できる
- **US6 (Phase 8)**: Foundational が前提。US6-1・SC-007 の網羅テスト(T060)は、全コマンド(T041〜T043、T047、T048、T051、T052、T055)の完了が前提。T061〜T070 は先に進めてよい
- **Polish (Phase 9)**: 必要なストーリーの完了が前提

### User Story Dependencies(完了の順序)

```text
Setup(T001 脅威モデル) → Foundational
                             ├─▶ US1 (P1) ─┬─▶ US2 (P1) ─▶ US4 の位置指定
                             │             ├─▶ US3 (P2)
                             │             └─▶ US4 (P2)
                             ├─▶ US5 (P2)(独立)
                             └─▶ US6 (P3)(T060 のみ全コマンドの後)
                                             └─▶ Polish
```

### Within Each User Story

- テストを先に書き、失敗することを確かめる
- ドメイン(Phase 2 で完了済み)→ コマンド/問い合わせ → 監査・イベントの確認
- ストーリーの Checkpoint を満たしてから次の優先度へ

### Parallel Opportunities

- Setup: T001 の完了後、T003〜T006、T008 は並行可
- Foundational: T009〜T012、T013・T014・T017・T018・T020・T022、T024・T027、T028・T030〜T033、T036・T037 は並行可
- 各ストーリーのテスト(`[P]` 付き)は並行可
- US5 は US1 と並行して進められる。US3 と US4 は US1 の後に並行できる

---

## Parallel Example: Foundational

```text
Task: "T013 値オブジェクトの単体テストを core/tests/unit/job/test_values.py に作成"
Task: "T018 状態遷移の単体テストを core/tests/unit/job/test_job_transitions.py に作成"
Task: "T020 待機列の単体テストを core/tests/unit/job/test_queue.py に作成"
Task: "T024 権限の判定の網羅テストを core/tests/unit/test_authorization.py に作成"
Task: "T036 標準ライブラリのみ・禁止 API の検査を core/tests/architecture/test_imports.py に作成"
Task: "T037 語彙検査を core/tests/architecture/test_vocabulary.py に作成"
```

## Parallel Example: User Story 1

```text
Task: "T038 受け入れテスト core/tests/acceptance/test_us1_submit_and_order.py"
Task: "T039 同時の提出の競合テスト core/tests/acceptance/test_concurrency_submit.py"
Task: "T044 性能の目安のテスト core/tests/perf/test_submit_perf.py"
```

## Parallel Example: User Story 6

```text
Task: "T060 受け入れテスト core/tests/acceptance/test_us6_audit_and_history.py"
Task: "T061 受け入れテスト core/tests/acceptance/test_us6_completion_events.py"
Task: "T062 イベントの契約テスト core/tests/contract/test_job_completed_event.py"
Task: "T063 保持期間のテスト core/tests/acceptance/test_retention.py"
Task: "T064 JSON Schema を core/src/job_core/job/schemas/job_completed.v1.json に配置"
Task: "T069 RetentionPolicy を core/src/job_core/job/domain/retention.py に実装"
```

---

## Implementation Strategy

### MVP First(User Story 1 のみ)

1. Phase 1: Setup(**T001 脅威モデルを先に完成**)
2. Phase 2: Foundational(すべてのストーリーをブロック)
3. Phase 3: US1
4. **STOP and VALIDATE**: `uv run pytest core/tests/acceptance/test_us1_submit_and_order.py core/tests/acceptance/test_concurrency_submit.py` と、アーキテクチャの検査が通ることを確認

### Incremental Delivery

1. Setup + Foundational → 基盤が完成
2. US1 → 検証(MVP: 並べて順番に実行)
3. US2 → 検証(順序の制御。既存の仕組みの不満の解消。P1 の完了)
4. US3、US4 → 検証(運用操作)
5. US5 → 検証(閲覧。003・006 の前提)
6. US6 → 検証(監査・イベント・保持。007 の前提)
7. Polish → `setup-dev.ps1 -VerifyOnly` で quickstart の全検証

### Parallel Team Strategy

1. 全員で Setup + Foundational
2. その後: A が US1 → US2 → US4、B が US5 → US6(T060 以外)、C が US1 完了後に US3
3. 最後に T060(全操作の監査の網羅)と Polish

---

## Notes

- `[P]` = 別のファイルで、未完了のタスクに依存しない
- `[USn]` = spec のユーザーストーリーへの対応
- 受け入れテストの名前に spec のシナリオ番号(`us1_1` など)を含め、spec との対応を追えるようにする
- フィールドの制約は data-model.md を正とし、タスクやコードのコメントに書き写さない
- 用途・プラットフォームの語を core に入れない(T037 が検出する)。禁止語の一覧は `forbidden_terms.txt` だけに置く
- タスクまたは論理的なまとまりごとにコミットする
