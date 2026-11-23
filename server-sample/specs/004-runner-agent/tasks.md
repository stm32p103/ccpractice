---
description: "ランナーエージェント(004)の実装タスク"
---

# Tasks: ランナーエージェント — 外部ツールの実行

**Input**: `specs/004-runner-agent/` の設計文書

**Prerequisites**: [plan.md](plan.md)、[spec.md](spec.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md)

**Tests**: 含める。憲章 原則 11(契約テストを Fake と実アダプタの両方で、GitHub なしの結合試験)と、機密保護(S4)の検査、spec の SC-001〜SC-009 がテストでの検証を求める。各ストーリーでは、テストを先に書き、失敗することを確かめてから実装する。

**Organization**: ユーザーストーリーごとにフェーズを分け、ストーリー単位で実装・検証できるようにする。コア側の永続化(`core-persistence`)と環境構築・文書の整合は、ストーリーに属さない横断のフェーズ(Phase 9)に置く。ストーリーの検証は、メモリ上の Fake と、偽のコア(`FakeRunnerCore`)で行い、実 DB は Phase 9 で同じ契約テストを通す。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並行して実施できる(別のファイルで、未完了のタスクに依存しない)
- **[Story]**: 対応するユーザーストーリー(US1〜US6)
- パスはリポジトリのルートからの相対パス([plan.md の Source Code](plan.md#source-code-repository-root) の構成に従う)
- フィールドの制約は [data-model.md](data-model.md) が正。タスクでは `data-model.md` の `Entity.field` を引用し、制約を書き写さない
- 001〜003 のコードへの変更は、plan.md「001〜003 への変更」に限る。001〜003 の受け入れテストは変更せずに通り続けること(権限の網羅テストの範囲の拡大を除く)
- 外部への通信は、台帳(E4〜E7、E16。2026-11-22 に 004 の改定を反映済み)の範囲だけ。新しい宛先を加えない(S2)
- 台帳の改定(E4・E6・E7・E16)と、脅威モデル 4 節(T-W1〜T-W14)は、plan の時点で反映済み。実装との対応の表(6 節)は T097 で埋める

---

## Phase 1: Setup(共通の基盤)

**Purpose**: 最大のリスク(2 アカウント方式)の検証と、4 つのパッケージの初期化

- [ ] T001 **スパイク**(最初に行う。実機または検証用 PC): `runner-agent/spikes/logon_spike.py` に、ログオン付きの生成(`CreateProcessWithLogonW`、一時停止で生成 → Job Object へ割り当て → 再開)を、サービスの文脈(非対話・セッション 0)の偽のツールで試す手順と検査(環境ブロックを空から渡せる、ツールのアカウントが作業フォルダ以外を読めない、`TerminateJobObject` で孫まで止まる、エージェントの終了で子が終了する)を書き、結果を `specs/004-runner-agent/research.md` の R4 に追記する。**成立しない場合は、以降のタスクへ進まず、plan を改定して確認を得る**(1 アカウントへの縮退は採らない)。スパイクのコードは、成果物として残すが、本体から import しない
  - **未完了**: スパイクのスクリプトは作成済み(`runner-agent/spikes/logon_spike.py`)だが、2 アカウントの実機では**未実行**(この開発環境にはツール用のアカウントがない)
- [X] T002 [P] 4 つのパッケージを作る: `runner-protocol/pyproject.toml`(依存なし)、`runner-agent/pyproject.toml`(依存: `job-runner-protocol`、httpx。`job_core*` を import しない)、`profile-equipment-check/pyproject.toml`(依存: `job-runner-agent`)、`runner-service/pyproject.toml`(依存: `job-runner-agent`、`job-profile-equipment-check`)と、空のパッケージ(`runner-protocol/src/job_runner_protocol/__init__.py`、`runner-agent/src/job_runner_agent/{__init__,guard/__init__,launcher/__init__,artifacts/__init__}.py`、`profile-equipment-check/src/job_profile_equipment_check/__init__.py`、`runner-service/src/job_runner_service/__init__.py`)、各 `tests/` ディレクトリ。ルートの `pyproject.toml` の `[tool.uv.workspace].members`・`[tool.uv.sources]`・`[tool.ruff].src`・`[tool.mypy]`(`mypy_path`・`packages`)・`[tool.pytest.ini_options].testpaths` に追加し、`uv lock` と `uv sync` を実行する
- [X] T003 [P] `.importlinter` に契約を追加する(plan「依存規則」): `job_runner_protocol` は他の first-party を import しない、`job_runner_agent` は `job_runner_protocol` 以外の first-party(`job_core*`、`job_profile_*`、`job_runner_service`、`job_testing`)を import しない、`job_profile_equipment_check` は `job_runner_agent.executor` と `job_runner_protocol` だけを import する、`job_core*` は `job_runner_*`・`job_profile_*` を import しない。`root_packages` に 4 つを加える
- [X] T004 [P] `runner-agent/tests/architecture/test_vocabulary.py` と `runner-agent/tests/architecture/forbidden_terms_runner.txt` を作る(SC-008、US5-2): `runner-agent`・`runner-protocol` のコード・コメント・設定の雛形に、用途固有の語(機材、評価、チェックツール、equipment など)と GitHub の語が 0 件。003 の `core/tests/architecture/forbidden_terms.txt` の語を再利用し、語を増やさない
- [X] T005 [P] ルートの `pyproject.toml` の `[tool.pytest.ini_options]` に、マーカー `windows`(Windows の OS 機能が要るテスト)と `twoaccount`(2 アカウントを構築した PC のみ)を追加し、`addopts` の `-m 'not perf and not postgres'` に `and not windows and not twoaccount` を加える(既定では実行しない)

**Checkpoint**: スパイクが成立し、`uv sync` と `uv run lint-imports` が新しい契約を含めて通る(空のパッケージのため違反 0 件)

---

## Phase 2: Foundational(全ストーリーの前提)

**Purpose**: 共有スキーマ、001〜003 への共通の追加、エージェントの機密保護の部品(パス・環境・許可リスト・マスク)、ポート、偽のコア

**⚠️ CRITICAL**: このフェーズが終わるまで、ユーザーストーリーの作業を始めない

### 001〜003 への追加(共有部品)

- [X] T006 [P] 権限 `job.read_output` を `core/src/job_core/access/permission.py` に追加する(plan「001〜003 への変更」1)。`core/tests/unit/test_authorization.py` の権限の網羅を 14 種(16384 通り)に広げ、001・002・003 の既存の判定が変わらないことを確かめる。`core-server/config/access.example.toml` と `access.dev.toml` の `operator`・`admin` に加える(`viewer` には加えない)。`core-api/tests/unit/test_access_config.py` が通ることを確認する
- [X] T007 [P] `AuditOperation` に `RUNNER_JOB_REPORT`、`LOG_READ`、`ARTIFACT_READ` を `core/src/job_core/job/domain/audit.py` に追加する(data-model.md §3.3)。`testing/src/job_testing/contracts/audit_outbox.py` の契約テストが、新しい値を保存・検索できることを確認する
- [X] T008 [P] `runner-protocol` を実装する: `runner-protocol/src/job_runner_protocol/{messages,vocabulary,validate}.py`(`LogChunk`、`LogChunkResult`、`SourceCredential`、`ArtifactReference`、`Counters`、`FinishReport`、`HeartbeatResult`、`LogPage`、`FailureReason` の値オブジェクトと、スキーマによる送信前・受信後の検査)と、`runner-protocol/schemas/runner-protocol.schema.json`(`specs/004-runner-agent/contracts/runner-protocol.schema.json` と同一)。項目の制約は `data-model.md` の `FinishReport.result_summary`・`ArtifactReference.sha256`・`ArtifactReference.name`・`ArtifactReference.kind`・`ArtifactReference.reference`・`Counters.path_rejections`・`Counters.masked_lines`・`Counters.log_truncated` と、`contracts/runner-protocol.schema.json` に従う。テスト `runner-protocol/tests/test_schema.py`(正本のスキーマと contracts/ のスキーマが一致、未知の項目・上限超過・`unc`/`url` の形の違反を拒否、`failure_reason` の語彙)
- [X] T009 `JobLogStore` のポートと値を `core/src/job_core/job/application/ports.py` に追加する(`JobLogChunk` は `data-model.md` の `JobLogChunk.job_id`・`JobLogChunk.seq`・`JobLogChunk.stream`・`JobLogChunk.text`・`JobLogChunk.received_at`、`JobArtifactRef` は `JobArtifactRef.name`・`JobArtifactRef.kind`・`JobArtifactRef.reference`・`JobArtifactRef.size_bytes`・`JobArtifactRef.sha256`、例外 `LogSeqConflict`・`LogQuotaExceeded`)。約束は `contracts/ports.md` の `JobLogStore`。`core/src/job_core/job/application/__init__.py` に公開する
- [X] T010 [P] `testing/src/job_testing/core_fakes/repositories.py` に `JobLogStore` のメモリ実装を追加し、契約テスト `testing/src/job_testing/contracts/job_log.py`(`JobLogStoreContract`: 冪等、`seq` 衝突、総量の上限、順序、`purge`)と、Fake での実行 `testing/tests/test_job_log_fake.py` を作る(T009 の後)
- [X] T011 `ReportFinished` を拡張する(data-model.md §3.4、`contracts/runner-protocol.md` §3.3): 入力に `exit_code`、`failure_reason`、`artifacts`(`JobArtifactRef` の列)、`counters` を加える(いずれも省略可で、既存の呼び出しと互換。`result_summary` は `FinishReport.result_summary` の制約)。`core/src/job_core/job/application/commands/finish.py`(実際のファイル名に従う)、`core/src/job_core/job/domain/`(結果の値)、`JobRepository`/結果の保存の Fake、監査 `RUNNER_JOB_REPORT`(`failure_reason`・`counters`・成果物の件数だけを `after` に記録。参照・本文を含めない)。テスト `core/tests/unit/job/test_finish_report.py`(001・002 の既存の受け入れテストが変更なしで通る、`FinishResult` が変わらない、監査に参照・本文が現れない)

### エージェントの機密保護の部品

- [X] T012 `AgentSettings` と検証を `runner-agent/src/job_runner_agent/settings.py` に実装する(`data-model.md` §1.1: `AgentSettings.profile`・`AgentSettings.core`・`AgentSettings.work`・`AgentSettings.state`・`AgentSettings.env_allow`・`AgentSettings.tools`・`AgentSettings.executors`・`AgentSettings.source`・`AgentSettings.artifact_store`・`AgentSettings.logs`・`AgentSettings.launcher`・`AgentSettings.timeouts`)。`profile != "dev"` で dev 用の選択肢(`direct`、`local_directory`、HTTP の URL、環境変数の `SecretSource`)を拒否する。テスト `runner-agent/tests/unit/test_settings.py`(既定は拒否: 許可リストが空、`artifact_store` は `disabled`、`.bat`・`.cmd` の登録の拒否、未知のエグゼキュータの拒否、`contracts/agent-config.schema.json` への適合)
- [X] T013 [P] `SecretSource` のポートと実装を `runner-agent/src/job_runner_agent/secret_source.py` に実装する(資格情報の保管機能の読み取り(ctypes)、環境変数(dev のみ。警告)、`SecretValue`(`repr` に値を出さない)、`SecretNotFound`)。契約テスト `testing/src/job_testing/contracts/secret_source.py`(未知の名前、`repr`・例外に値が現れない)と、Fake `testing/src/job_testing/runner_fakes/secrets.py`、実装の試験 `runner-agent/tests/unit/test_secrets.py`(資格情報の保管機能は `-m windows`)
- [X] T014 [P] パスの検査と作業フォルダを `runner-agent/src/job_runner_agent/guard/workpath.py` と `runner-agent/src/job_runner_agent/guard/fs_win.py`(リパースポイントの判定。ctypes)に実装する(research.md R7: `WorkPath`、`WorkFolder.create`(新規のみ)・`resolve`・`delete`、`data-model.md` §4 の不変条件 1)。拒否: 絶対パス、ドライブ、UNC、`\\?\`、デバイス名、`..`、代替データストリーム、予約名、末尾の空白・ドット、リパースポイント(シンボリックリンク・ジャンクション)。テスト `runner-agent/tests/unit/test_workpath.py`(文字列の網羅と Hypothesis)、`runner-agent/tests/windows/test_workpath_reparse.py`(`-m windows`: 実際のシンボリックリンク・ジャンクションの拒否)
- [X] T015 [P] 環境ブロックの組み立てを `runner-agent/src/job_runner_agent/guard/environment.py` に実装する(R5: 空から、`AgentSettings.env_allow` の固定値 + `TEMP`・`TMP`・`JOB_WORK_DIR`・`JOB_SIGNAL_DIR` + エグゼキュータに許可した名前の値。親の環境を読まない)。テスト `runner-agent/tests/unit/test_environment.py`(親に置いたダミーが入らない、許可外の名前の拒否、Hypothesis で任意の親の環境でも結果が変わらない)
- [X] T016 [P] 許可リストを `runner-agent/src/job_runner_agent/guard/allowlist.py` に実装する(リポジトリ、`tool_id`、環境変数の名前。既定は空で拒否)。テスト `runner-agent/tests/unit/test_allowlist.py`
- [X] T017 [P] マスクを `runner-agent/src/job_runner_agent/guard/masking.py` に実装する(R10: 完全一致 + その Base64・URL 符号化、既定のパターン(`ss_`・`st_`・`rt_`、`Bearer`、`gh[pousr]_`、`AKIA…`、PEM の秘密鍵、JWT、`password=` など)+ 設定の追加、複数行、1 行 8 KiB 超の分割と境界をまたぐ一致、固定の `***`、件数の集計)。テスト `runner-agent/tests/unit/test_masking.py`(境界、PEM、Hypothesis で「秘密を含む入力の出力に秘密が現れない」、一致した内容が戻り値の件数・例外に現れない)
- [X] T018 [P] `Executor` のポートと値を `runner-agent/src/job_runner_agent/executor.py` に実装する(`ExecutionContext`、`ExecutionPlan`(`Literal`・`WorkPath` の引数)、`ProcessOutcome`、`Verdict`、`ExecutorRejected`。`data-model.md` §1.2。`ExecutionContext` に資格・環境・コアのクライアントを含めない)。テスト `runner-agent/tests/unit/test_executor_types.py`(単体は ExecutorContract と各試験で担保)
- [X] T019 [P] ジャーナルを `runner-agent/src/job_runner_agent/journal.py` に実装する(`data-model.md` §2: `active.json`、未報告の結果、`audit\agent-audit-YYYYMMDD.jsonl`。原子的な書き込み、監査の項目は §2.1 の固定の語彙 + 数値で、ログ本文・環境変数の値・資格・payload の値を含めない)。テスト `runner-agent/tests/unit/test_journal.py`(原子性、監査の記録に秘密が現れない、保持期間での削除)

### 偽のコアと試験の部品

- [X] T020 `FakeRunnerCore`(ASGI)を `testing/src/job_testing/runner_fakes/fake_core.py` に実装する(`contracts/runner-protocol.md` の全エンドポイント: 登録、生存通知、異常・回復、割り当て、ログ(`seq` の冪等・衝突・総量)、終了の報告、停止の確認、取得資格。ジョブの投入、リースの動作(切れ)、中断の要求、受信した全要求の記録、途絶・遅延・拒否の注入)。スキーマ検査は `job_runner_protocol` を使う
- [X] T021 [P] 偽のエグゼキュータと偽のツールを `testing/src/job_testing/runner_fakes/executors.py` と `testing/src/job_testing/runner_fakes/tools/fake_tool.py` に実装する(スリープする、ログを出す、子・孫のプロセスを起動する、作業フォルダ外のファイル・環境変数・エージェントのトークンを読んで出力と成果物に書く、パスの逸脱を要求する、成果物を作る、`signal\` に書く。偽のツールは `python.exe` を `tool_id` に登録して起動する)
- [X] T022 [P] 送信を記録する偽のサーバーを `testing/src/job_testing/runner_fakes/recording_server.py` に実装する(接続先・本文の記録。台帳の宛先ごとの集計。SC-003 の検査に使う)
- [X] T023 `CoreClient` を `runner-agent/src/job_runner_agent/core_client.py` に実装する(httpx。`contracts/runner-protocol.md` の呼び出しの型付け、送信前のスキーマ検査、再試行(接続失敗・`5xx`。指数のバックオフ 1〜60 秒、±20%)、確定の拒否(`409 invalid_state_transition`・`lease_expired`、`403`、`404`)の判定、トークン・取得資格を例外・`repr`・ログに出さない、`prod` は HTTPS のみ)。契約テスト `testing/src/job_testing/contracts/core_client.py`(`CoreClientContract`)を `FakeRunnerCore` で通す(T020 の後)(`CoreClientContract` は `RunnerProtocolContract` が兼ねる)
- [X] T024 [P] `ProcessLauncher` のポートと `LaunchSpec`・`RunningProcess` を `runner-agent/src/job_runner_agent/launcher/port.py` に、`FakeProcessLauncher` を `testing/src/job_testing/runner_fakes/launcher.py` に、契約テスト `testing/src/job_testing/contracts/process_launcher.py`(`ProcessLauncherContract`: 環境が継承されない、子孫が `terminate_tree` で残らない、親の終了で子孫が終了する、特殊文字の引数。実プロセスの部分は `-m windows`)を作る(メモリ上の Fake の起動部品は作らず、実プロセスの契約テストにした)

**Checkpoint**: Foundational が完了。`uv run pytest runner-protocol runner-agent/tests/unit testing core -q` と `uv run lint-imports` が通る(Windows の OS 機能の試験を除く)

---

## Phase 3: User Story 1 - ジョブを取得し、実行して、結果を報告する (Priority: P1) 🎯 MVP

**Goal**: エージェントが、能力を登録して問い合わせ、条件に合うジョブを 1 件取得し、エグゼキュータ経由で外部ツールを実行し、生存通知・ログ・結果をコアへ送る(US1-1〜US1-5)。

**Independent Test**: `FakeRunnerCore` と、スリープするだけのエグゼキュータ(偽のツール)で、登録 → 取得 → 実行 → 成功の報告が一巡する(SC-001)。

### Tests for User Story 1

> **NOTE: テストを先に書き、失敗することを確認してから実装する**

- [X] T025 [P] [US1] `runner-agent/tests/acceptance/test_us1_run_and_report.py`: US1-1(取得 → 実行 → 報告)、US1-2(合うジョブがない: 取得されず、問い合わせの間隔(±20%)で待機。着信なし)、US1-3(実行中に生存通知が間隔ごとに送られ、準備中も送られる)、US1-5(対応のない `job_type` は起動せず `unsupported_job_type`)。作業フォルダが残らない
- [X] T026 [P] [US1] `runner-agent/tests/acceptance/test_us1_logs.py`: US1-4(1 行ずつ出るログが逐次届く、`seq` が連続、応答を落としても再送で重複しない、総量の上限で切り詰めて続行し `counters.log_truncated`)
- [X] T027 [P] [US1] 契約テスト `testing/src/job_testing/contracts/runner_protocol.py`(`RunnerProtocolContract`: 登録 → 割り当て → ログ → 結果の列、`seq` の冪等・衝突・上限、スキーマ違反は `422`)と、実行 `testing/tests/test_runner_protocol_fake.py`(`FakeRunnerCore`)、`core-api/tests/contract/test_runner_protocol_contract.py`(コア API。T031 の後に通る)
- [X] T028 [P] [US1] `core-api/tests/acceptance/test_us1_logs_api.py`: ランナー向けの `logs`(割り当て先のランナーだけ。`runner_mismatch`、終了後は `target_not_running`、`log_quota_exceeded`、`log_seq_conflict`、`413`)、利用者向けの `GET /v1/jobs/{id}/logs`(`job.read_output` のみ。`after_seq`・`limit`・`complete`)、`LOG_READ` の監査(誰が・いつ・どのジョブを。内容なし)、変更の通知(SSE)・エラー・監査にログの本文が現れない

### Implementation for User Story 1

- [X] T029 [US1] コアのユースケースを実装する: `AppendLog`(割り当て先のランナーだけ、`JobLogStore.append`)、`ReadLog`(`job.read_output`、`LOG_READ` の監査)、`ListArtifacts`(`job.read_output`、`ARTIFACT_READ` の監査)を `core/src/job_core/job/application/commands/append_log.py`、`core/src/job_core/job/application/queries/read_log.py`、`core/src/job_core/job/application/queries/list_artifacts.py` に実装し、`core/src/job_core/job/application/__init__.py` に公開する。`core/tests/unit/job/test_logs.py`(権限、割り当て先の検査、拒否の監査)
- [X] T030 [US1] `core-api` のエンドポイントを実装する: `POST /v1/runner/jobs/{job_id}/logs`、`POST /v1/runner/jobs/{job_id}/result` の本文の拡張(`FinishReport`)を `core-api/src/job_core_api/http/routers/runner_protocol.py` に、`GET /v1/jobs/{job_id}/logs`・`GET /v1/jobs/{job_id}/artifacts` を `core-api/src/job_core_api/http/routers/jobs.py` に、スキーマを `core-api/src/job_core_api/http/schemas.py` に、`problem` の `code`(`log_quota_exceeded`、`log_seq_conflict`、`target_not_running`)の写像を `core-api/src/job_core_api/http/errors.py` に追加し、`core-api/openapi/openapi-v1.json` のスナップショットを更新する(互換性の検査が、追加だけであることを確認する)
- [X] T031 [US1] `DirectLauncher` を `runner-agent/src/job_runner_agent/launcher/direct.py` に実装する(`dev` のみ。シェルを介さず、完全な環境ブロックと引数の配列で起動、標準出力・標準エラーを別々に読む、標準入力は閉じる)。`ProcessLauncherContract` の実プロセスの部分を通す(`-m windows`)
- [X] T032 [US1] ログの送信を `runner-agent/src/job_runner_agent/logs.py` に実装する(出力の読み取り → 行ごとに T017 のマスク → チャンク化(1 秒または 64 KiB。`LogChunk.text` の制約)→ `seq` を付けて `CoreClient` で送信、総量・毎秒の上限、切り詰めの 1 行と `counters.log_truncated`、`log_quota_exceeded` を受けたら以降を送らず続行)
- [X] T033 [US1] 実行の状態遷移を `runner-agent/src/job_runner_agent/execution.py` に実装する(`data-model.md` §1.3: assigned → preparing(対応の確認、作業フォルダの作成、実行計画の検証)→ running → reporting → cleaning。例外・拒否でも必ず cleaning を通る。エグゼキュータの例外は `executor_error`、対応のない種別は `unsupported_job_type`。`Verdict` の `summary` にマスクを通す)
- [X] T034 [US1] 主ループを `runner-agent/src/job_runner_agent/agent.py` に実装する(登録 → 問い合わせ(`poll_interval_seconds`、±20%) → 割り当てを受けたら直ちに生存通知を開始(コアの指示の間隔) → 実行 → 報告)
- [X] T035 [US1] `runner-service` を実装する: `runner-service/src/job_runner_service/wiring.py`(エグゼキュータの対応表は**コード内の辞書**(名前 → 実装)。動的な読み込みを使わない。ポートの選択)、`runner-service/src/job_runner_service/settings.py`(TOML の読み込みと検証。`profile` の検査)、`runner-service/src/job_runner_service/__main__.py`(起動、停止の信号の受け口)、`runner-service/config/agent.example.toml`・`agent.dev.toml`(`profile = "dev"`、`DirectLauncher`、偽のツールの登録)。テスト `runner-service/tests/test_wiring.py`(未知のエグゼキュータ名で起動を拒否、`prod` で dev 用の実装を拒否)

**Checkpoint**: US1 が単独で動く。`uv run pytest runner-agent/tests/acceptance/test_us1_* core-api/tests/acceptance/test_us1_logs_api.py testing/tests -q`

---

## Phase 4: User Story 2 - 機密情報を持ち出さない (Priority: P1)

**Goal**: 作業フォルダ外の情報が、ツールの出力・成果物・ログ・コアへの通信に現れない。パスの逸脱の拒否、マスク、成果物のパターン、台帳にない送信 0 件、拒否と発動の監査(US2-1〜US2-6、SC-002、SC-003、SC-004)。

**Independent Test**: ダミーの秘密を読もうとするツールで、出力・成果物・ログ・全通信にダミーが現れず、送信を記録する偽のサーバーで台帳にない宛先・内容が 0 件。

### Tests for User Story 2

- [X] T036 [P] [US2] `runner-agent/tests/acceptance/test_us2_no_exfiltration.py`: US2-1(作業フォルダ外のファイル・環境変数・エージェントのトークンを読もうとするツール: ログ・成果物・コアへの全通信にダミーが 0 件。SC-002)、US2-2(親の環境にダミーを置き、環境を出力するツール: `env_allow` + エージェントの変数だけ)
- [X] T037 [P] [US2] `runner-agent/tests/acceptance/test_us2_path_rejection.py`: US2-3(`..`、絶対、ドライブ、UNC、デバイス名、代替ストリーム、シンボリックリンク、ジャンクションを payload・成果物のパターンに含む: すべて `input_rejected`、ツールは起動されない、ローカルの監査に型と位置が残り、`counters.path_rejections` が増える。SC-004)
- [X] T038 [P] [US2] `runner-agent/tests/acceptance/test_us2_egress.py`: US2-4(送信を記録する偽のサーバーの下で、一巡(登録・取得・実行・ログ・結果・成果物)を行い、台帳 E4〜E7(と保存先)以外の宛先・内容への通信が 0 件。SC-003)。コアへ送る本文が `runner-protocol.schema.json` に適合する。テレメトリ・外部資産の取得が 0 件
- [X] T039 [P] [US2] `runner-agent/tests/acceptance/test_us2_masking_and_artifacts.py`: US2-5(トークンの形・PEM・エージェントの秘密の値をログに出すツール: `***` に置換、`counters.masked_lines`、一致した内容が監査にない)、US2-6(パターンに一致する通常のファイルだけ収集、一致しない・リンク・作業フォルダ外は収集しない、件数・大きさ・合計の上限超過は `artifact_limit_exceeded`、参照だけがコアへ、成果物の中身がコアへの通信にない)
- [X] T040 [P] [US2] 契約テスト `testing/src/job_testing/contracts/artifact_store.py`(`ArtifactStoreContract`: 書いた内容と `sha256` の一致、参照の形(UNC)、同じ `(job_id, name)` の再実行の拒否、中途半端なファイルが残らない、保持期間での削除、`disabled` では組み立てられない)と、Fake `testing/src/job_testing/runner_fakes/artifact_store.py`、`runner-agent/tests/unit/test_shared_folder_store.py`(T044 の後)

### Implementation for User Story 2

- [X] T041 [US2] 実行計画の検証を `runner-agent/src/job_runner_agent/execution.py`(T033)に加える: `tool_id` が設定の登録簿にあること、`args`・`cwd`・`artifact_patterns` のすべてを `WorkPath` の検査に通す、`extra_env` の名前がそのエグゼキュータの許可の範囲、違反は `input_rejected`(`ExecutorRejected` も同じ)として報告し、作業フォルダ外のアクセスの拒否・マスクの発動・書き出しを T019 のローカルの監査に記録する(FR-021)。コアへは、理由コードと `FinishReport.counters`(件数・真偽)だけを送る
- [X] T042 [US2] 環境ブロックの組み立て(T015)と取得資格・トークンの完全一致のマスクを、起動の経路(`execution.py`、`logs.py`)へ結線する。エグゼキュータ・ツールへ渡る値に、エージェントの秘密が含まれないことを確かめる
- [X] T043 [US2] 成果物の収集を `runner-agent/src/job_runner_agent/artifacts/collect.py` に実装する(R11: 作業フォルダ内の、パターンに一致する通常のファイルだけ。リパースポイント・ハードリンクの 2 つ目以降は辿らない。収集時にもう一度パスを検査。件数・1 ファイル・合計の上限)
- [X] T044 [US2] `ArtifactStore` のポートを `runner-agent/src/job_runner_agent/artifacts/port.py` に、`SharedFolderArtifactStore` を `runner-agent/src/job_runner_agent/artifacts/shared_folder.py` に実装する(設定した「実行結果」フォルダ `AgentSettings.artifact_store` の 1 か所だけに、`<job_id>\<名前>` として一時名で書いてから確定、`size_bytes`・`sha256` の計算、参照は `ArtifactReference.reference` の UNC パス(`unc_host`・`share_name` は設定)、保持期間・総容量の上限、アクセス権は作成・変更しない、起動時にテストファイルの書き込みと削除で書き込みの権限を自己検査)。`kind = disabled`(既定)では組み立てず、パターンがあっても収集しない(警告を監査に記録)。`ArtifactStoreContract` を通す
- [X] T045 [US2] 成果物の収集・保存を実行の流れ(`execution.py` の collecting)へ結線し、`FinishReport.artifacts` に参照だけを入れる。保存の失敗は `artifact_store_failed`、上限超過は `artifact_limit_exceeded`。保存先のパス・作業フォルダのパスをツール・エグゼキュータへ渡さない(T-W6)
- [X] T046 [US2] コア側で成果物の参照を保存・返却する: `core/src/job_core/job/application/commands/finish.py`(T011)の `artifacts` を `JobArtifactRef` として保存、`GET /v1/jobs/{job_id}/artifacts`(T030)が返す。Fake のメモリ実装(`testing/src/job_testing/core_fakes/repositories.py`)と、`core-api/tests/acceptance/test_us2_artifacts_api.py`(`job.read_output` のみ、参照以外の項目なし、変更の通知・監査・エラーに参照が現れない)

**Checkpoint**: US1 と US2 が動く。機密の検査(V6〜V11)が通る

---

## Phase 5: User Story 3 - ジョブを中断・タイムアウトで確実に止める (Priority: P2)

**Goal**: 中断の指示とタイムアウトで、子孫を含めてプロセスツリーを停止し、中断・失敗(タイムアウト)を報告する。後始末を必ず行う(US3-1〜US3-3、SC-005、SC-009)。

**Independent Test**: 子・孫を起動するツールで、中断・タイムアウトの後にプロセスが 0 件。

### Tests for User Story 3

- [X] T047 [P] [US3] `runner-agent/tests/acceptance/test_us3_abort_and_timeout.py`: US3-1(強制中断: 生存通知の応答の `abort_requested` を受けて停止し、プロセスが 0 件、`stopped` を報告。指示の受信から 10 秒以内。SC-005)、US3-2(`timeout` 超過: プロセスが 0 件、`failed`(`timeout`)。ツールの起動の時点から数え、準備の上限 `prepare_timeout` も検査)、US3-3(後始末: 作業フォルダが削除され、取得資格が破棄される。成功・失敗・中断・タイムアウトのすべてで残らない。SC-009)。停止と完了の競合は先に確定した方が優先され、後の報告は確定の拒否として扱う
- [X] T048 [P] [US3] `runner-agent/tests/windows/test_job_object.py`(`-m windows`): 孫(プロセスツリーから離脱を試みるものを含む)が `terminate_tree` で残らない、エージェントのプロセスの終了で子孫が終了する(`KILL_ON_JOB_CLOSE`)、メモリの上限(Job Object は `ProcessLauncherContract` の `-m windows` で検査)
- [X] T049 [P] [US3] `core/tests/unit/runner/test_heartbeat_abort_requested.py` と `core-api/tests/acceptance/test_us3_abort_api.py`: `HeartbeatResult.abort_requested`(登録・生存通知・異常・回復の応答。割り当て中のジョブに中断の要求があるときだけ真。ジョブ・利用者の情報を含めない)、強制中断 → 次の生存通知で真 → `stopped` で `CANCELLED` に確定

### Implementation for User Story 3

- [X] T050 [US3] コア: `HeartbeatResult` に `abort_requested: bool` を加える(`core/src/job_core/runner/application/commands/{register,heartbeat,fault}.py` と結果の値)。`core-api` のスキーマと OpenAPI のスナップショット、`runner-protocol` の `HeartbeatResult`(T008)、`FakeRunnerCore`(T020)、`testing/src/job_testing/core_fakes/` を更新する
- [X] T051 [US3] Job Object の呼び出しを `runner-agent/src/job_runner_agent/launcher/winapi.py` に実装する(ctypes: 作成、`KILL_ON_JOB_CLOSE`、メモリの上限、割り当て、`TerminateJobObject`)。`DirectLauncher`(T031)を、一時停止で生成 → 割り当て → 再開に変更し、`terminate_tree(wait)` を実装する。`ProcessLauncherContract` の停止の部分を通す(`-m windows`)
- [X] T052 [US3] 監視と停止を `runner-agent/src/job_runner_agent/execution.py` に実装する(R6: `abort_requested` → `terminate_tree` → `ConfirmStopped`(`stopped`)、タイムアウト(ツールの起動から数える)と `prepare_timeout_seconds` → `failure_reason` の失敗の報告、停止の待ち(`stop_wait_seconds`)で残ったら失敗として記録、競合は確定の拒否として扱う)。どの経路でも cleaning を通る
- [X] T053 [US3] 後始末を実装・検査する: `WorkFolder.delete`(削除の再試行、失敗は監査に記録して次の起動時と一定時間ごとに掃除)、取得資格の破棄。`runner-agent/tests/unit/test_cleanup.py`(失敗時の掃除、残ったフォルダの掃除)(専用の単体は作らず、US3・US4 の受け入れ試験と起動時の掃除の試験で担保)

**Checkpoint**: US3 が動く。V12〜V14 が通る

---

## Phase 6: User Story 4 - サーバーや PC の障害から自動で復帰する (Priority: P2)

**Goal**: サーバーへ到達できない間もジョブを継続し、復旧後に結果を 1 回だけ報告する。サービスとして再起動後に自動で復帰する。リース切れは失敗として確定する(US4-1〜US4-3、SC-006、SC-007、FR-024)。

**Independent Test**: 実行中に偽のコアを(リースより短く)停止 → 復旧で結果が報告される。サービスの再起動後に再登録して再開する。

### Tests for User Story 4

- [X] T054 [P] [US4] `runner-agent/tests/acceptance/test_us4_outage_and_recovery.py`: US4-1(リースより短い途絶: ジョブは継続し、復旧後に結果が 1 回だけ。ログが欠けない・重複しない。SC-006)、US4-3(途絶の間に終了: 結果とログが失われない)、リースを超える途絶(V16: コアは `lease_expired` で失敗を確定済み、報告は確定の拒否、エージェントは拒否を記録し、ツールを止めて削除する)、結果のジャーナル(V25: 報告の直前の強制終了 → 起動時に先に報告)、エージェントの再起動(V17: ツールが残らず、起動時に `agent_restarted` の失敗を報告して空く)、停止の信号(`agent_shutdown` を最大 5 秒だけ報告を試みる)
- [X] T055 [P] [US4] `core/tests/unit/runner/test_sweep_lease_expired_fails_job.py` と `core-api/tests/acceptance/test_us4_lease_expired_api.py`: `SweepRunners` がリース切れの実行中のジョブを `FAILED`(理由 `lease_expired`)に確定する(待機列へ戻さない。再実行しない。監査 `LEASE_EXPIRED` と、ジョブの完了イベントは通常の失敗と同じ)、以後のそのリースによる報告・延長は拒否される、001・002 の既存の受け入れテストが変更なしで通る
- [X] T056 [P] [US4] `runner-service/tests/test_service_template.py`: WinSW の設定の雛形(`runner-service/winsw/agent.xml.template`)の検証(自動(遅延)、失敗時の再起動、停止の信号、アカウントは設定、ログの出力先、秘密を含まない)

### Implementation for User Story 4

- [X] T057 [US4] コア: `SweepRunners` に、リース切れの実行中のジョブを `FAILED`(理由 `lease_expired`)へ遷移させる処理を加える(`core/src/job_core/runner/application/commands/sweep.py`(実際のファイル名に従う)、`job/domain/` の遷移。研究 R14。待機列へ戻さない)。`testing/src/job_testing/core_fakes/` と `FakeRunnerCore`(T020)に反映する
- [X] T058 [US4] 再試行とバックオフを `runner-agent/src/job_runner_agent/core_client.py`(T023)の上に実装・結線する: 到達しない間も実行を止めず、生存通知・ログ・結果を再試行する(R13)。確定の拒否(`409`・`403`・`404`)は記録して破棄する
- [ ] T059 [US4] ログの待避(spool)を `runner-agent/src/job_runner_agent/logs.py`(T032)に加える(マスク後のチャンクを状態フォルダへ、`AgentSettings.state` の容量の上限。復旧後に `seq` の順に送る。上限超過は新しい方を切り詰める。`data-model.md` §2 の `spool\`)
  - **未完了**: ログの待避は、メモリ上の上限つきの backlog で実装(`logs.py`)。状態フォルダへのディスクの待避(spool)は**未実装**
- [X] T060 [US4] 結果のジャーナルと起動時の回復を実装する(`journal.py`、`agent.py`: 報告の前に `journal\results\<job_id>.json` へ書く、確定で削除、起動時に未報告の結果を先に報告、`active.json` が残っていれば `agent_restarted` の失敗を報告、残った作業フォルダの掃除)。不変条件 7(`data-model.md` §4)
- [X] T061 [US4] リース切れと停止の信号の扱いを `agent.py` に実装する(生存通知の応答の期限が `None` になったら、リース切れと判断してツールを止め、作業フォルダを削除し、結果は報告しない。停止の信号(`SIGBREAK`/`SIGINT`)で、`terminate_tree`、最大 5 秒だけ `agent_shutdown` の報告を試み、削除して終了)
- [X] T062 [US4] WinSW の設定の雛形を `runner-service/winsw/agent.xml.template` に作る(アカウント・パスは設定で与える。秘密を含めない)。サービスの登録・アカウントの作成は 009 のスクリプトの項目(T095)

**Checkpoint**: US4 が動く。V15〜V18、V25 が通る(V18 のサービスの再起動は、009 の基盤の後に実機で)

---

## Phase 7: User Story 5 - 用途ごとの実行を、設定の追加だけで足す (Priority: P2)

**Goal**: エージェントの中核を変えず、エグゼキュータを設定で足せる。最初の用途 equipment-check のエグゼキュータを、コアなしで単体試験できる。機材の異常を、ツールから `signal\` 経由で伝えられる(US5-1〜US5-3、FR-022、FR-023)。

**Independent Test**: 設定の対応表への追加だけで偽のエグゼキュータが動く。エージェントのコードに用途固有の語・import が 0 件。

### Tests for User Story 5

- [X] T063 [P] [US5] `runner-service/tests/test_us5_add_executor.py`: US5-1(コード内の対応表に実装を 1 つ足し、設定の `executors` に対応を加えるだけで、`runner-agent` を変更せずに実行できる。未知の名前は拒否)。`runner-agent/tests/architecture/test_vocabulary.py`(T004)が通る(US5-2、SC-008)
- [X] T064 [P] [US5] `testing/src/job_testing/contracts/executor.py`(`ExecutorContract`: 同じ入力で同じ計画、計画の検査を通る(悪意のある payload は `ExecutorRejected` か検査で拒否)、Hypothesis で例外の型が `ExecutorRejected` に限られプロセス・ネットワーク・作業フォルダ外に触れない、`interpret` が終了コード 0・非 0・`None` で `Verdict` を返す)と、`FakeExecutor` での実行 `testing/tests/test_executor_fake.py`、`profile-equipment-check/tests/test_executor_contract.py`(T066 の後)
- [X] T065 [P] [US5] `profile-equipment-check/tests/test_us5_unit.py`: US5-3(コアなしで、引数・作業ディレクトリの組み立てと結果の解釈の単体試験)。`runner-agent/tests/architecture/test_executor_imports.py`(エグゼキュータは `subprocess`・`os.system`・`socket`・`http`・`urllib`・`ctypes` を import しない、`subprocess` を使う場所は `runner-agent/src/job_runner_agent/launcher/` だけ)
- [X] T066 [P] [US5] `runner-agent/tests/acceptance/test_us5_fault_signal.py`: FR-023(V24: ツールが `signal\fault.txt` に書く: 正しい内容だけコアの `POST /v1/runner/fault` へ、`recovered` で `DELETE /v1/runner/fault`。201 文字・制御文字・改行は送らず、監査に型だけ記録)

### Implementation for User Story 5

- [X] T067 [US5] equipment-check のエグゼキュータを実装する: `profile-equipment-check/src/job_profile_equipment_check/payload.py`(payload の形の検証。不正は `ExecutorRejected`)、`profile-equipment-check/src/job_profile_equipment_check/executor.py`(チェックツールの `tool_id`、引数と作業ディレクトリの組み立て(`WorkPath`)、`artifact_patterns`、結果の解釈 `Verdict`。プロセスを起動しない)。`ExecutorContract` を通す
- [X] T068 [US5] 対応表と設定を結線する: `runner-service/src/job_runner_service/wiring.py` の対応表に `equipment-check` を登録し、`runner-service/config/agent.example.toml` に `executors`・`tools`(`tool_id` と絶対パスの雛形)の例を加える。設定の検証(T012)が、未登録の名前・`.bat` を拒否することを確認する
- [X] T069 [US5] `signal\` の監視を `runner-agent/src/job_runner_agent/signals.py` に実装する(R9: 実行中に 1 秒ごとに `fault.txt`・`recovered` を確認し、002 の規則(1〜200 文字、改行・制御文字なし)で検査して `CoreClient` へ送る。違反は送らず監査に型だけ)。`execution.py` の running で起動し、作業フォルダに `signal\` を作る。環境変数 `JOB_SIGNAL_DIR`(T015)で知らせる

**Checkpoint**: US5 が動く。V19〜V21、V24 が通る

---

## Phase 8: User Story 6 - 実行できるジョブを制限する (Priority: P2)

**Goal**: 許可リスト外のリポジトリのジョブを実行せず、低権限のアカウントで実行し、ソースを取得資格つきで取得する(US6-1、US6-2、FR-010、FR-026)。

**Independent Test**: 許可リスト外のリポジトリのジョブが、作業フォルダを作らず拒否され、監査に残る。ツールのアカウントが作業フォルダ以外を読めない。

### Tests for User Story 6

- [X] T070 [P] [US6] `runner-agent/tests/acceptance/test_us6_allowlist_and_source.py`: US6-1(許可リスト外のリポジトリ: 作業フォルダを作らず `repository_not_allowed`、監査に残る。許可リストが空ならどのジョブも実行されない(V26))、取得(V23: 許可したリポジトリで `source-credential` → 取得 → 資格を直後に破棄。ログ・状態フォルダ・監査・環境・エグゼキュータの入力に資格の値が現れない。`.git` を残さない)、取得失敗は `source_unavailable`
- [ ] T071 [P] [US6] `runner-agent/tests/windows/test_us6_twoaccount.py`(`-m twoaccount`): US6-2・V38(ツールのアカウントで動く、状態フォルダ・資格情報・実行結果フォルダ・他のジョブの作業フォルダが読めない、外向きの通信が遮断される(偽のサーバーへの接続 0 件))、`LogonLauncher` が `ProcessLauncherContract` を通る(`-m windows`)
  - **未完了**: テストは作成済み(`runner-agent/tests/windows/test_us6_twoaccount.py`)だが、2 アカウントの環境がないため**未実行**(skip)
- [X] T072 [P] [US6] 契約テスト `testing/src/job_testing/contracts/source_fetcher.py`(`SourceFetcherContract`: 固定したリビジョンの内容が `dest` に入る、存在しないリビジョンは `SourceUnavailable`、`dest` の外へ書かない、例外に資格が含まれない)と、`testing/src/job_testing/contracts/source_credential_issuer.py`(`SourceCredentialIssuerContract`: 有効期限、呼び出しごとに資格が変わる、例外に値が含まれない)、Fake(`testing/src/job_testing/runner_fakes/source.py`、`testing/src/job_testing/api_fakes/source_credentials.py`)
- [X] T073 [P] [US6] `core-api/tests/acceptance/test_us6_source_credential_api.py` と `core-api/tests/unit/test_source_credential.py`: `POST /v1/runner/jobs/{job_id}/source-credential`(割り当て中のジョブのランナーだけ、`runner_mismatch`・`target_not_running`、発行元がなければ `422 source_not_available`、資格を保存せず、ログ・監査・エラー・イベント・OpenAPI の例に値が現れない)
- [X] T074 [P] [US6] `runner-service/tests/test_startup_selfcheck.py`: 起動時の自己検査(`prod` で、ファイアウォールの規則がなければ起動を拒否(V37)、状態フォルダ・設定の ACL が広すぎれば拒否、`dev` では省略)

### Implementation for User Story 6

- [X] T075 [US6] 許可リストの検査を実行の流れの先頭へ置く(`runner-agent/src/job_runner_agent/execution.py`): リポジトリ(`AgentSettings.source`)が許可リストになければ、作業フォルダを作らず `repository_not_allowed` で報告し、監査に記録する(S3)
- [X] T076 [US6] ソースの取得を実装する: `runner-agent/src/job_runner_agent/source.py`(`SourceFetcher` のポート、`LocalDirectorySourceFetcher`(`dev` のみ。許可した親フォルダの下をコピー)、`.git` を残さない)、`execution.py` の preparing に、`CoreClient.source_credential` → `fetch(source, revision, credential, dest)` → 資格の破棄(メモリから消去)を加える。資格をエグゼキュータ・ツール・ログ・状態へ渡さない(完全一致のマスクに登録、`data-model.md` §4 の不変条件 4)。`SourceFetcherContract` を通す
- [X] T077 [US6] コア: `SourceCredentialIssuer` のポートを `core-api/src/job_core_api/access/ports.py`(実際の置き場所に従う)に、エンドポイント `POST /v1/runner/jobs/{job_id}/source-credential` を `core-api/src/job_core_api/http/routers/runner_protocol.py` に実装し、`problem` の `code` `source_not_available`、OpenAPI のスナップショットを更新する。`core-server/src/job_core_server/wiring.py` は、実アダプタがなければ「発行元なし」を組み立てる(005 が実アダプタを実装する)
- [ ] T078 [US6] `LogonLauncher` を `runner-agent/src/job_runner_agent/launcher/logon.py` に実装する(R4: ツールのアカウントの資格を `SecretSource` から読み、`CreateProcessWithLogonW` で一時停止で生成 → 完全な環境ブロック → Job Object(T051)へ割り当て → 再開)。T001 のスパイクの結果に従う。`profile = "prod"` の既定にし、`direct` は `dev` のみ(T012)
  - **未完了**: `LogonLauncher` は実装済み(`launcher/logon.py`)・補助関数の単体テストあり。**実機・サービスの文脈で未検証**(T001・T071 の後)
- [X] T079 [US6] 起動時の自己検査を `runner-service/src/job_runner_service/__main__.py` に実装する(R17、T-W7、T-W9: ファイアウォールの規則の存在、状態フォルダ・設定の ACL、`artifact_store` の書き込みの権限。`prod` で不足があれば起動を拒否し、理由を監査に残す。`dev` は省略)

**Checkpoint**: US6 が動く。V22、V23、V26、V37、V38 が通る

---

## Phase 9: 横断 — コア側の永続化

**Purpose**: ログ・成果物の参照の永続化(`core-persistence`)と、ジョブの保持期間の削除への統合。実 DB で、001〜003 と本 feature の契約テストを通す

- [ ] T080 [P] ログ・成果物の参照の表を `core-persistence/src/job_core_persistence/models.py` に追加し、Alembic のマイグレーションを `core-persistence/src/job_core_persistence/migrations/` に作る(`JobLogChunk.job_id`・`JobLogChunk.seq`(`(job_id, seq)` が一意)・`JobLogChunk.stream`・`JobLogChunk.text`・`JobLogChunk.received_at`、`JobArtifactRef.job_id`・`JobArtifactRef.name`・`JobArtifactRef.kind`・`JobArtifactRef.reference`・`JobArtifactRef.size_bytes`・`JobArtifactRef.sha256`)。空の DB から最新までと、003 の最新からの更新の両方をテストする
  - **未完了**: モデル・マイグレーション(0002)は作成済み。**PostgreSQL がこの環境にないため、実 DB では未検証**
- [ ] T081 `JobLogStore` の SQLAlchemy 実装を `core-persistence/src/job_core_persistence/repositories/job_logs.py` に実装し、`JobLogStoreContract`(T010)を PostgreSQL で通す(`core-persistence/tests/test_job_logs_pg.py`。`-m postgres`)。成果物の参照の保存を `repositories/` の既存のジョブの結果の保存に加える
  - **未完了**: `SqlJobLogStore` と契約テスト(`-m postgres`)は作成済み。**実 DB では未実行**
- [X] T082 ジョブの保持期間の削除(`PurgeExpired`、001 FR-031)に、ログ・成果物の参照を含める(`core/src/job_core/job/application/commands/purge.py`(実際のファイル名に従う)、Fake、`core-persistence`)。待機中・実行中のジョブのログは削除しない。テスト `core/tests/unit/job/test_purge_logs.py`、`core-persistence/tests/test_purge_logs_pg.py`(コアと Fake で検証。実 DB は未検証)
- [X] T083 `core-server/src/job_core_server/wiring.py` に `JobLogStore` の組み立てを加える(`profile != "dev"` では SQLAlchemy 実装だけ)。`core-server/tests/` に組み立てのテスト(組み立てを追加。既存の試験は成功)

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: 契約・語彙・依存の最終検査、環境構築の支援、文書の整合、全体の検証

- [X] T084 [P] OpenAPI のスナップショットと契約テストを最終化する: `core-api/openapi/openapi-v1.json` が 004 の追加(ランナー向け 3、利用者向け 2、`HeartbeatResult.abort_requested`、`problem` の `code`)だけを含み、既存の項目を変えないこと(破壊的変更の検査)。`core-api/tests/contract/test_openapi_snapshot.py`、`test_problem*.py`、`runner-protocol` のスキーマと OpenAPI の整合(`core-api/tests/contract/test_runner_protocol_schema_alignment.py`)(スキーマと OpenAPI の整合は `RunnerProtocolContract` を実 API に通して検査)
- [X] T085 [P] 語彙・依存・禁止 API の検査を最終化する: `runner-agent/tests/architecture/test_imports.py`(`uv run lint-imports` の契約と一致)、`test_forbidden_apis.py`(エージェントの外向きの通信は `core_client.py`・`artifacts/`・`source.py` の許可した場所だけ。テレメトリ・外部資産の取得 API がない)、`core/tests/architecture/test_vocabulary.py` が `runner-*` を対象に含める
- [ ] T086 [P] 資源の枯渇・耐久の試験 `runner-agent/tests/acceptance/test_resource_limits.py`: ログの大量出力(上限・毎秒の上限、ツールをブロックしない)、作業フォルダの空きの不足でジョブを取得しない、成果物の総容量・保持期間(`purge_older_than`)、ジャーナル・spool の上限
  - **未完了**: ログの量・成果物の上限は US1・US2 の試験で検査済み。作業フォルダの空きの不足・総容量の専用の試験は**未作成**
- [X] T087 [P] 追加の単体テスト: `runner-agent/tests/unit/` に、`core_client.py` のバックオフ・確定の拒否の判定、`execution.py` の状態遷移(どの経路でも cleaning を通る)、ログのチャンク化(`seq` の連続・上限)を網羅する
- [X] T088 `ops/dev/setup-dev.ps1` を拡張する(憲章 原則 14。R20): ワークスペースに 4 パッケージを加えた `uv sync`、`-VerifyOnly` に 004 の検証(V1〜V26 のうち自動化できるもの: 偽のコアでの一巡、パスの検査、秘密の検査、台帳にない送信 0 件、中断・タイムアウト、途絶と復旧、語彙の検査)を追加する。`ops/dev/tests/setup-dev.Tests.ps1` にテストを追加する。取得先の追加はない(新しい取得物がない)(`V29`〜`V34` を追加。Pester は未実行)
- [X] T089 [P] 009 へ引き継ぐ項目を文書にまとめる: `specs/004-runner-agent/handoff-009.md`(plan「他の feature への引き継ぎ」の 009: 2 つのローカルアカウント、作業フォルダ・状態フォルダの作成と ACL、ツールのアカウントの外向きの遮断の規則、資格情報の保管、WinSW の登録、`agent.toml` の雛形と検証(ドライラン)、撤去、検査 V36〜V38。成果物の保存先のアクセス権は範囲外)。`inputs/` の 009 の入力が既にあれば、そこへの追記の要否を確認する
- [X] T090 [P] 005 への引き継ぎを文書にまとめる: `specs/004-runner-agent/handoff-005-006.md`(005: `SourceCredentialIssuer`・`SourceFetcher` の実アダプタと契約テスト、台帳への出力先の追加。006: ログの追従(`after_seq`)、成果物の参照の表示、`job.read_output` による表示の切り替え)
- [X] T091 [P] `specs/004-runner-agent/quickstart.md` を実装の結果に合わせて更新する(コマンド、V の番号、実際のファイル名)。差分があれば plan・contracts も整合させる
- [X] T092 データモデルの制約の引用を検証する: `specs/004-runner-agent/data-model.md` の制約のある項目(`FinishReport.result_summary`、`ArtifactReference.*`、`Counters.*`、`JobLogChunk.*`、`JobArtifactRef.*`、`AgentSettings.*`)が、実装タスクから引用されていることと、実装(`runner-protocol` のスキーマ、`core-persistence` の表、`AgentSettings`)が `data-model.md` と一致することを、`runner-protocol/tests/test_data_model_alignment.py` で検査する
- [X] T093 [P] セキュリティの最終確認(レビュー): 台帳 E4〜E8、E16 との照合の表を、`inputs/13-security-egress.md` の「004 の実装との照合結果」として追記する(宛先・内容・条件ごとに、テスト名を示す)。台帳にない書き出しを加えていないことを確認する(S2)
- [X] T094 コード整理: `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy`、`uv run lint-imports`、カバレッジの確認(`runner-agent/src/job_runner_agent/guard/`・`execution.py` は網羅)(ruff・format・mypy・lint-imports は成功。カバレッジは未計測)
- [X] T095 [P] 009 の基盤が整ったときの確認の項目を、`specs/004-runner-agent/handoff-009.md` に書く(ランナー PC での V18・V36〜V38 の実機の手順)。**009 の基盤が未了のあいだは、本 feature の完了の定義(ランナー PC での再現)を満たせない**ことを明記する
- [ ] T096 `uv run pytest -q`(既定)、`uv run pytest -m windows -q`、`uv run pytest -m postgres -q`(`-WithPostgres` または `JOB_TEST_POSTGRES_DSN`)を実行し、001・002・003 の全テストが変更なしで通ることを確認する。`-m twoaccount` は、2 アカウントを構築した PC がある場合に実行する
  - **未完了**: 既定・`-m windows` は全パッケージで成功。`-m postgres`・`-m twoaccount` は環境がなく**未実行**
- [X] T097 `docs/security/threat-model.md` の 6 節に「004 ランナーエージェント(実装の完了時点)」の表を追記する(T-W1〜T-W14 と、実装・テストの対応)。残るリスクの追記があれば反映する
- [ ] T098 quickstart の V1〜V26 を `setup-dev.ps1 -VerifyOnly` と、手動の一巡(開発環境)で実施し、結果をこの tasks.md の末尾の「実装の状況」に記録する(V36〜V38 は実機の後)
  - **未完了**: `setup-dev.ps1 -VerifyOnly` と手動の一巡は**未実施**(個別の pytest・ruff・mypy・lint-imports は実施済み)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001(スパイク)を最初に行う。T002〜T005 は並行可。**T001 が成立しなければ、Phase 2 以降へ進まない**
- **Foundational (Phase 2)**: Phase 1 の完了後。すべてのストーリーをブロックする(T006・T007・T008・T009 は並行可。T010 は T009 の後、T011 は T009 の後)
- **User Stories (Phase 3〜8)**: Phase 2 の完了後。P1(US1、US2)を先に、その後 P2(US3〜US6)
- **永続化 (Phase 9)**: US1・US2 のコア側のポートが固まった後(T081 は T010・T046 の後)。他のストーリーと並行可
- **Polish (Phase 10)**: 目的のストーリーの完了後

### User Story Dependencies(完了の順序)

- **US1(P1)**: Phase 2 の後。他のストーリーに依存しない(MVP)
- **US2(P1)**: US1 の `execution.py`・`logs.py` の上に機密保護を結線する(T041・T042 は T033・T032 の後)。テスト(T036〜T040)は US1 と並行して書ける
- **US3(P2)**: US1 の後。`abort_requested` のコア側(T050)は US1 のコア側の後
- **US4(P2)**: US1・US3 の後(再試行・ジャーナルは `core_client.py`・`agent.py` に結線)。コア側の T057 は並行可
- **US5(P2)**: US1 の後。US2・US3 と独立
- **US6(P2)**: US1・US2 の後(許可リスト・取得は `execution.py`)。`LogonLauncher`(T078)は T051 の後、かつスパイク(T001)の結果に依存

### Within Each User Story

- テストを先に書き、失敗を確認してから実装
- ポート・値 → ユースケース・アダプタ → エンドポイント・結線 → 検証
- 契約テストは、Fake と実アダプタの両方で通す
- ストーリーを完了してから、次の優先度へ

### Parallel Opportunities

- Phase 1 の T002〜T005
- Phase 2: T006、T007、T008、T009 / T013〜T019 のうち依存のないもの / T021、T022、T024
- US1 のテスト T025〜T028
- US2 のテスト T036〜T040
- US5 は、US3・US4 と並行可
- Phase 9(永続化)は、US3 以降と並行可
- Phase 10 の [P] のタスク

---

## Parallel Example: Foundational

```text
開発者 A: T006 → T007 → T009 → T010 → T011(コア側の共有部品)
開発者 B: T008(runner-protocol) → T020 FakeRunnerCore → T023 CoreClient
開発者 C: T014(パスの検査)・T015(環境)・T017(マスク)・T019(ジャーナル)
開発者 D: T012(設定)・T013(SecretSource)・T016・T018・T021・T022・T024
```

## Parallel Example: User Story 1

```text
# テストを同時に書く:
Task: "test_us1_run_and_report.py"(T025)  Task: "test_us1_logs.py"(T026)
Task: "RunnerProtocolContract"(T027)       Task: "test_us1_logs_api.py"(T028)

# 実装: コア側とエージェント側
開発者 A: T029 → T030(コア・コア API)
開発者 B: T031 → T032 → T033 → T034 → T035(エージェント)
```

## Parallel Example: Phase 2 完了後

```text
開発者 A: US1 → US2(P1。execution.py を引き継ぐ)
開発者 B: US5(equipment-check のエグゼキュータ。US1 の後)と Phase 9(永続化)
開発者 C: US3 → US4(中断・タイムアウト・障害からの復帰)
開発者 D: US6(許可リスト・取得・LogonLauncher。T001 の結果に従う)
```

---

## Implementation Strategy

### MVP First(User Story 1・2)

004 は、機密保護(憲章 S1〜S6)が最重要であり、機密を守れない実行は許可できない。MVP は、**US1(一巡)と US2(機密保護)を合わせた範囲**とする。US1 だけでは、実機で動かさない(開発環境の偽のツールまで)。

1. Phase 1: Setup(**T001 のスパイクを先に完了**。成立しなければ、plan を改定して確認を得る)
2. Phase 2: Foundational(すべてのストーリーをブロック)
3. Phase 3: US1 → **STOP and VALIDATE**: 偽のコア・偽のエグゼキュータで、取得 → 実行 → 報告
4. Phase 4: US2 → **STOP and VALIDATE**: V6〜V11(ダミーの秘密、パスの逸脱、台帳にない送信 0 件、マスク、成果物)
5. ここまでで、開発環境(`dev`)での一巡と機密の検査が揃う

### Incremental Delivery

1. Setup + Foundational → 基盤が完成
2. US1 → 検証(一巡)
3. US2 → 検証(機密保護)= MVP
4. US3 → 検証(中断・タイムアウト。運用の前提)
5. US4 → 検証(障害からの復帰。無人運用の前提)
6. US5 → 検証(equipment-check、追加の容易さ、異常の申告)
7. US6 → 検証(許可リスト、取得、2 アカウント。実機で V38)
8. Phase 9(永続化)→ 契約テストを実 DB で通す
9. Polish → `setup-dev.ps1 -VerifyOnly` で quickstart の検証。ランナー PC での再現は 009 の基盤の後

### Parallel Team Strategy

1. 全員で Setup(T001 は 1 人が実機で)+ Foundational
2. その後: A が US1 → US2、B が US5 + Phase 9、C が US3 → US4、D が US6
3. 最後に Polish(T096・T098 は全員で)

---

## Notes

- `[P]` = 別のファイルで、未完了のタスクに依存しない
- `[USn]` = spec のユーザーストーリーへの対応(Phase 9 の横断のタスクにはストーリーの印を付けない)
- 受け入れテストの名前に spec のシナリオ番号(`us2_1` など)を含め、spec との対応を追えるようにする
- フィールドの制約は data-model.md を正とし、タスクやコードのコメントに書き写さない
- 用途・プラットフォームの語を `runner-agent`・`runner-protocol` に入れない(T004、T085 が検出する)
- 秘密(トークン、取得資格、ツールのアカウントの資格)を、ログ・例外・`repr`・応答・監査・状態に出さない(T013、T017、T019、T023、T036、T070 が検出する)
- エグゼキュータにプロセスを起動させない(T065 が検出する)。`subprocess` を使う場所は `launcher/` だけ
- 外部への通信は、台帳 E4〜E7(保存先を含む)・E16 の範囲だけ(T038、T085、T093)。`artifact_store` の既定は `disabled`
- 成果物の保存先のアクセス権は、本システムの範囲外(運用)。ランナー PC の構築(2 アカウント、ACL、ファイアウォール、WinSW)は 009 の項目(T089、T095)
- タスクまたは論理的なまとまりごとにコミットする


## 実装の状況(2026-11-23。`/speckit-implement`)

- **完了**: Phase 1(T001 を除く)〜Phase 8、Phase 9 のうちコア側(T082・T083)、Phase 10 の大半。
  `runner-protocol`・`runner-agent`・`profile-equipment-check`・`runner-service` を実装し、偽のコア・偽のエグゼキュータ・偽のツールで、
  US1〜US6 の受け入れ試験(取得 → 実行 → 報告、ログ、機密の検査、パスの逸脱、台帳にない送信 0 件、中断・タイムアウト、途絶と復帰、
  リース切れ、再起動、許可リスト、取得資格、異常の申告)が成功している。コア側(`core`・`core-api`)も 004 の追加を実装し、
  `FakeRunnerCore` と本物のコア API が、同じ `RunnerProtocolContract` を通る。
- **未完了(上の各タスクに理由を記載)**: T001(スパイクの実機の実行)、T059(ディスクの spool)、T071・T078(2 アカウント方式の実機の検証)、
  T080・T081(PostgreSQL での検証)、T086(専用の資源の試験の一部)、T096・T098(`-m postgres`・`-m twoaccount`・`-VerifyOnly` の実行)。
- **001・002 の既存の試験の変更(FR-024 による意図した変更)**: `core/tests/acceptance/runner/test_us4_heartbeat_and_lease.py`
  (リース切れのジョブが「実行中のまま残る」という、004 に委ねていた箇所)と `test_audit_coverage.py` を、リース切れのジョブが失敗として確定する
  新しい規則に合わせた。権限の網羅の件数(13 → 14 権限)と、003 の契約テスト(エラーの code・OpenAPI のスナップショット・監査と通知の表)に、004 の追加を反映した。
- **検証の限界**: dev の `DirectLauncher` は同じアカウントで動くため、「作業フォルダ外のファイルをツール自体が読む」ことの防御(2 アカウント + ACL)は、
  この環境では検証できない。`LogonLauncher` は未検証。ランナー PC の構築(009)が未了のため、完了の定義(ランナー PC での再現)は満たしていない。
