# Data Model: ランナーエージェント

**Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md) | **Date**: 2026-11-22

用途固有の語を含まない。永続の保存先は 2 つ: (1) エージェントの**状態フォルダ**(エージェントのアカウントだけが読み書きできる)、(2) コア側の**ログ・成果物の参照の表**(core-persistence)。作業フォルダの中身は、ジョブの終了で消える。

## 1. エージェントの内部の型(`job_runner_agent`。値オブジェクトを中心にする)

### 1.1 設定(`AgentSettings`。起動時に検証して不変)

[contracts/agent-config.schema.json](contracts/agent-config.schema.json) が形を定める。主な項目:

| 項目 | 型 | 検証・既定 |
|---|---|---|
| `profile` | `prod` \| `dev` | 既定 `prod`。`dev` でだけ `DirectLauncher`・`LocalDirectorySourceFetcher`・HTTP の URL・環境変数の `SecretSource` を許可 |
| `core.url` / `core.runner_token_secret` | URL / 資格情報の名前 | `prod` は HTTPS のみ。トークンの値は設定に書かない |
| `poll_interval_seconds` | 数 | 1〜60。既定 5(±20% のゆらぎ) |
| `capabilities` | 申告(002 のスキーマ) | 許可リスト外のキーはコアが登録ごと拒否する |
| `work.root` / `work.min_free_bytes` | パス / 数 | 絶対パス。空きが下回ったらジョブを取得しない |
| `state.dir` | パス | 絶対パス。ACL の自己検査の対象 |
| `env_allow` | 名前 → 固定の値 | 親の環境の値は読まない(R5) |
| `tools` | `tool_id` → 実行ファイルの絶対パス | `.bat`・`.cmd` は不可。ファイルの存在を起動時に確認 |
| `executors` | `job_type` → `{executor, tool_ids, env_names, options}` | `executor` はコード内の対応表の名前(R1)。未知の名前は起動を拒否 |
| `source.repository_allowlist` / `source.fetcher` | 一覧 / `local_directory`(dev のみ)など | 空なら、どのジョブも実行しない(既定は拒否) |
| `artifact_store` | `kind` = `disabled`(既定)\|`shared_folder`\|`https_storage` と各設定 | 上限(件数・大きさ・合計・保持期間・総容量)を持つ(R11) |
| `logs` | 上限、送信間隔、マスクのパターン | R10 |
| `launcher` | `logon`(`prod`)\|`direct`(`dev` のみ)、ツールのアカウントの資格の名前 | R4 |
| `timeouts` | `prepare_timeout_seconds`(既定 600)、`stop_wait_seconds`(5) | R6 |
| `firewall_self_check` | 真偽 | `prod` は既定で真 |

### 1.2 ジョブの実行の流れの型

| 型 | 項目 | 備考 |
|---|---|---|
| `Assignment`(003 の応答) | `job_id`、`definition`(`job_type`、`payload`、`timeout_seconds`、`source`、`revision` ほか)、`lease_id`、`lease_expires_at` | payload を解釈するのはエグゼキュータだけ |
| `ExecutionContext` | `job_id`、`job_type`、`payload`(読み取り専用)、`timeout`、`work`(`WorkFolderView`)、`source_dir`(`WorkPath`)、`options`(設定の値) | エグゼキュータへ渡す。**資格・環境・コアのクライアントを含まない** |
| `WorkPath` | 作業フォルダ内の相対パス(検査済みの値) | 検査は `WorkFolder.resolve()` だけが作る(R7) |
| `ExecutionPlan` | `tool_id`、`args: list[Literal \| WorkPath]`、`cwd: WorkPath`、`artifact_patterns: list[str]`、`extra_env: Mapping[str,str]` | エグゼキュータの出力。エージェントが検証してから起動 |
| `ProcessOutcome` | `exit_code \| None`、`stopped_by`(`none`\|`abort`\|`timeout`\|`shutdown`\|`lease_lost`)、`duration`、`output_truncated` | 起動したプロセスの結果 |
| `Verdict` | `succeeded`、`failure_reason \| None`、`summary \| None`(≤ 200 文字) | エグゼキュータの出力。`summary` はマスクを通る。既定の解釈: `exit_code == 0` なら成功 |
| `ArtifactReference` | `name`、`kind`(`unc`\|`url`)、`reference`、`size_bytes`、`sha256` | コア API へ送る唯一の成果物の情報 |
| `FinishReport` | `outcome`、`exit_code`、`failure_reason`、`result_summary`、`artifacts`、`counters` | 003 の `result` の拡張([contracts](contracts/runner-protocol.md)) |
| `Counters` | `path_rejections`、`masked_lines`、`log_truncated` | **件数と真偽だけ**。内容を含まない |

`failure_reason` の語彙(固定): `tool_failed`、`timeout`、`input_rejected`、`executor_error`、`unsupported_job_type`、`repository_not_allowed`、`source_unavailable`、`artifact_limit_exceeded`、`artifact_store_failed`、`prepare_timeout`、`agent_shutdown`、`agent_restarted`、`lease_expired`(コアが付ける)。

### 1.3 状態の遷移(エージェント側の `Execution`)

```
idle → assigned → preparing(許可リスト・作業フォルダ・取得・計画の検証)
     → running(ツールの実行・ログ・信号の監視)
     → collecting(成果物の収集・保存)
     → reporting(ジャーナルへ書き → 報告)
     → cleaning(作業フォルダ・資格の破棄)→ idle
```

- `assigned`〜`running` の間、中断・タイムアウト・リース切れ・停止の信号で、`stopping`(Job Object の終了)へ移り、`reporting`(中断なら `stopped`、他は失敗)へ進む。
- どの状態からでも、最終的に `cleaning` を通る(作業フォルダの削除、資格の破棄)。例外・拒否でも通る。
- 同時に存在する `Execution` は 1 つ。

## 2. 状態フォルダの永続の内容(エージェントのアカウントだけ)

| 名前 | 内容 | 保持 |
|---|---|---|
| `journal\active.json` | 割り当て中のジョブ(`job_id`、`lease_id`、開始時刻)。起動時に残っていたら、`agent_restarted` を報告する(R14) | 実行の間だけ |
| `journal\results\<job_id>.json` | 未報告の `FinishReport`(報告の確定まで) | 確定で削除 |
| `spool\<job_id>\*.json` | 未送信のマスク後のログのチャンク(`seq`、`stream`、`text`) | 送信で削除。容量の上限あり |
| `audit\agent-audit-YYYYMMDD.jsonl` | エージェントの監査の記録(下) | 90 日(設定) |

書き込みは、一時ファイルへ書いてからの置き換えで原子的に行う。

### 2.1 エージェントの監査の記録(ローカル。詳細は PC の外へ出さない)

項目: `at`、`job_id`、`event`、`code`、`detail`(短い固定の語彙 + 数値。**ログの本文・環境変数の値・資格・ペイロードの値を含まない**)。
`event`: `path_rejected`(拒否した種類と、要素の位置。パスの文字列は先頭 200 文字まで)、`mask_applied`(件数)、`repository_rejected`、`tool_not_registered`、`env_name_rejected`、`artifact_pattern_rejected`、`artifact_limit`、`fault_signal_rejected`、`work_folder_cleanup_failed`、`report_rejected`(確定の拒否の `code`)、`stopped`(理由)。
コア API へは、これらの**件数と理由コード**だけを、結果の `counters` と `failure_reason` として送る。コアは、それを監査ログの 1 件(`RUNNER_JOB_REPORT`。下の 3.3)に記録する。

## 3. コア側の追加(001〜003 への小さな変更)

001〜003 の公開の振る舞い・受け入れテストを壊さない追加に限る。

### 3.1 権限

- `job.read_output`(ジョブのログ・成果物の参照)を権限に加える(14 種になる。001・002・003 の網羅テストは 16384 通りに広がる。既存の判定は変わらない)。
- 003 の `access.example.toml`・`access.dev.toml` に、`operator`・`admin` のロールへ加える例を示す。`viewer` には加えない(001 の「すべての利用者が状態・要約・経緯を見られる」は変えない。ログ・成果物は、権限のある者だけ)。

### 3.2 ログと成果物の参照

| 型 / 表 | 項目 | 備考 |
|---|---|---|
| `JobLogChunk` | `job_id`、`seq`(0 以上)、`stream`(`stdout`\|`stderr`)、`text`(最大 64 KiB)、`received_at` | `(job_id, seq)` が一意。同じ `seq` の再送は、同じ内容なら受理(冪等)、異なる内容なら拒否 |
| `JobLogStore`(ポート) | `append(job_id, runner_id, chunk)`、`read(job_id, after_seq, limit)`、`purge(job_id)`、`size(job_id)` | 総量の上限(既定 10 MiB/ジョブ)を超えたら、追加を受理せず(`log_quota_exceeded`。エージェントは切り詰めて続ける)。ジョブの保持期間(001 FR-031)と同じ期間で削除 |
| `JobArtifactRef` | `job_id`、`name`、`kind`、`reference`、`size_bytes`、`sha256` | 結果の報告と同時に保存。中身は持たない |

- ログ・成果物の参照は、**割り当て中のジョブのランナーだけ**が追加できる(`runner_mismatch`)。終了後(または割り当て解除後)の追加は拒否する(`target_not_running`)。
- イベント(003 の `change-event`)・監査・エラー・通知・書き戻しへ、ログの本文・参照を載せない(003 T-A8、001 T-5 を維持)。

### 3.3 監査の操作の追加

`RUNNER_JOB_REPORT`(結果の報告の受理。`failure_reason`、`counters`、成果物の件数を `after` に持つ。参照・本文は持たない)、`LOG_READ`・`ARTIFACT_READ`(利用者によるログ・成果物の参照。誰が・いつ・どのジョブを)。

### 3.4 ほかの変更

- `HeartbeatResult` に `abort_requested: bool`(割り当て中のジョブに中断の要求があるか)を加える。
- `SweepRunners`: リース切れで失敗が確定するジョブ(実行中)を `FAILED`(理由 `lease_expired`)に遷移させる(R14)。ジョブの完了イベント・監査は、通常の失敗と同じ。
- `ReportFinished` の入力に、`exit_code`、`failure_reason`、`artifacts`、`counters` を加える(`result_summary` は 200 文字までに制限)。
- `SourceCredentialIssuer`(core-api のポート): `issue(job_id, source, revision) → SourceCredential(kind, secret, expires_at)`。実アダプタは 005、Fake は testing。資格は保存しない。

## 4. 不変条件(検査する)

1. 作業フォルダ外のパスを、外部ツールの引数・作業ディレクトリ・成果物として扱わない(R7)。
2. 外部ツールの環境ブロックは、`env_allow` + エージェントの定める変数 + エグゼキュータの許可した名前だけ。親の環境の変数が 1 つも入らない。
3. コア API へ送る項目は、[runner-protocol.schema.json](contracts/runner-protocol.schema.json) の項目だけ(`additionalProperties: false`)。ログ以外の自由な文字列は、`result_summary`(≤ 200 文字、マスク済み)と、異常の説明(≤ 200 文字。002)だけ。
4. 取得資格は、メモリの上にだけ存在し、取得の後に消去する。ログ・状態フォルダ・監査・環境・エグゼキュータへ渡さない。
5. ジョブの終了時に、作業フォルダと(ジョブの)取得資格が残らない。
6. 同じ `(job_id, seq)` のログは、コアに 1 度だけ保存される。
7. 結果の報告は、確定(受理または確定の拒否)まで、ジャーナルから失われない。
