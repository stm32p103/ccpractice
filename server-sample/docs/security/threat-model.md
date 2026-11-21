# 脅威モデル

**版**: 0.1(2026-11-21) | **根拠**: 憲章 S6(実装前に脅威モデルを明文化する) | **対象の初版**: 001 コア(ジョブの受付・キュー管理)

本書は、誰を信頼し、何から守るかを定める。最初の実装(001)の前に、core の信頼境界を確定する。
004(ランナーエージェント)、005(GitHub 連携)などの範囲は節だけを設け、各 feature の plan で追記する。

---

## 1. 守るもの

| # | 資産 | 例 | 主に守る性質 |
|---|---|---|---|
| A1 | ジョブの payload・定義 | 用途ごとの実行の指示 | 機密性(外部へ出さない)、完全性 |
| A2 | 待機列の順序とジョブの状態 | 誰のジョブがいつ実行されるか | 完全性(権限のない変更・偽の終了を防ぐ) |
| A3 | 監査ログ | 誰が・いつ・何をしたか | 完全性・否認防止(改ざん・削除を防ぐ) |
| A4 | 実行 PC の作業フォルダ外の情報 | ファイル、環境変数、資格情報 | 機密性(憲章 S1。004/005 の範囲) |

## 2. 信頼の前提

| # | 前提 | 担当 |
|---|---|---|
| P1 | core に渡される主体(`Principal`)と権限の集合は、呼び出し元が認証・認可の対応付けを済ませたものである。core は認証しない(FR-024) | 003(認証のアダプタ、ランナーごとのトークン) |
| P2 | ランナーの操作で渡される `runner_id` は、呼び出し元のランナーの主体に対応する(ランナーのトークンと `runner_id` の結び付けは 003 が保証する) | 003 |
| P3 | 永続化(DB)の管理者・バックアップの保管先は信頼する。DB への直接の書き込みは、運用の権限を持つ者に限られる | 003、008、009 |
| P4 | 実行するツールと、実行を許可するリポジトリは信頼できるものに限る(許可リスト。憲章 S5) | 004、005 |

## 3. 脅威と対策(001 コア)

| # | 脅威 | 対策 | 担保するタスク・テスト | 残るリスク |
|---|---|---|---|---|
| T-1 | **権限の偽装・昇格**: 権限のない主体が、他人のジョブの取り消し・移動・位置を指定した追加を行う | 可否を権限(permission)だけで判定する純粋な関数に集約し、主体の種類やロール名では判定しない(原則 9)。全組み合わせを網羅してテストする | T024、T025(SC-006) | P1 が破られた場合(呼び出し元が誤った権限を渡す)は防げない → 003 のテストで担保 |
| T-2 | **提出代行の名義の偽装**: サービスでない主体が、他人の名義でジョブを提出する | 名義が自分でない提出には `job.submit_on_behalf` を要する。名義上の提出者と、実際に提出した主体の両方を記録する | T025、T038 | 代行の権限を持つサービスの侵害 → 003 でトークンの失効を提供 |
| T-3 | **ランナーによる報告の偽装**: 割り当て先でないランナーが、他のジョブの終了・停止を報告し、結果を偽る | 終了の報告・停止の確認は `job.execute` を要し、さらに報告した `runner_id` が `Job.assigned_runner_id` と一致しなければ `RunnerMismatch` で拒否し、監査ログに `DENIED` を残す | T019、T043、T052、T038、T049 | P2 が破られた場合は防げない。割り当て先のランナー自身の侵害は防げない(004 の脅威モデルで扱う) |
| T-4 | **監査ログの改ざん・削除** | 監査ログのポートは追記のみ(変更の操作を持たない)。削除は保持期間による一括削除だけで、`retention.purge` を要し、削除の実行自体も監査ログに残す。ジョブの保持期間より短く設定できない(FR-032) | T022、T032、T063、T070 | DB への直接の書き込み(P3)は防げない。改ざん検知(ハッシュの連鎖など)は今回は行わない |
| T-5 | **イベント経由の漏洩**: ジョブ完了イベントに payload・ログ本文が混入し、通知先(外部)へ出る | イベントの項目を JSON Schema で固定し(`additionalProperties: false`)、payload・結果の要約を型として持てない。任意の payload で値が現れないことを property-based テストで確認する(FR-030) | T017、T062、T064、T065 | 通知の送信側(007)が別の情報を付け加えること → 007 の plan で担保 |
| T-6 | **core からの直接の外部送信**: core のコードがネットワーク・外部プロセスを使い、情報を持ち出す | core は標準ライブラリのみに依存し、`socket`・`http`・`urllib`・`subprocess` などの import を禁止する。依存規則を CI で検査する(FR-028、FR-029) | T005、T036、T074 | 動的な import による回避は検査の対象外(レビューで確認) |
| T-7 | **待機列の不整合による実行の取り違え**: 同時の操作で、取り消したジョブが割り当てられる、同じジョブが 2 回割り当てられる | 集約の `version` による楽観的排他と、判定からのやり直し。待機列と待機中のジョブの一致を契約テストで検査する | T026、T029、T031、T039、T046、T050 | 実アダプタ(core-persistence)が排他の約束を破る → 同じ契約テストを実アダプタでも実行する |
| T-8 | **開発環境・CI での取得物の改ざん**(サプライチェーン) | 取得先を公式の配布元と PyPI に限り(書き出し台帳 E15)、版を固定し、ハッシュ(配布物の SHA-256、`uv.lock`)で検証する。CI は `contents: read` のみで Secrets を使わない | T002、T006、T007、T074 | 公式の配布元自体の侵害は防げない |

## 3A. 脅威と対策(002 ランナー管理)

**根拠**: 憲章 S5・S6、書き出し台帳 E4・E16、002 の spec / research R9・R12・R13・R18。
002 の範囲では、ランナーの本人性は「ランナーごとのトークン」だけに依る。ランナー PC と、その上のツール・設定は信頼の前提とする(P4)。

**誰を信頼するか(002 の追加の前提)**

| # | 前提 | 担当 |
|---|---|---|
| P5 | ランナーのトークンは、権限を持つ利用者が作成時・再発行時に受け取り、ランナー PC の保護された場所に置く。置き場所の保護は、PC の ACL と運用(009、004)に依る | 004、009 |
| P6 | トークンを運ぶ通信は、イントラネット内で保護される(伝送の保護)。core は伝送を扱わない | 003 |
| P7 | ランナー PC の内部で動作するツールは、ランナー(エージェント)を通じてだけ異常を申告する。ツールから PC の外へは送らない(台帳 E4、E8) | 004 |

| # | 脅威 | 対策 | 担保するタスク・テスト | 残るリスク |
|---|---|---|---|---|
| T-R1 | **トークンの漏えい・再利用**: トークンが盗まれ、第三者がランナーとして振る舞う。保存先(DB)や監査ログ・応答からトークンが読み取られる | 256 ビットの乱数を発行時に 1 度だけ返し、保存は SHA-256 のハッシュだけ。照合は定数時間の比較。失効・再発行で旧トークンは直ちに使えない。トークンの値・ハッシュを、戻り値(発行以外)・監査記録・例外・`repr` に出さない | T005、T021、T022、T026、T059、T057、T058 | 漏えいに気付くまでの間の悪用は防げない(監査ログで気付く)。P5・P6 が破られた場合は防げない |
| T-R2 | **別のランナーへのなりすまし**: あるランナーのトークンで、別のランナーとして登録・生存通知・申告・割り当ての要求をする | 認証した主体の `subject_id` と、操作の `runner_id` が一致しなければ `RunnerMismatch` で拒否し、監査ログに `DENIED` を残す。トークンは 1 台のランナーに結び付く | T025、T026、T057 | 同じランナーの正規のトークンを持つ者の操作は区別できない |
| T-R3 | **トークンによる権限の昇格**: ランナーのトークンで、ランナーの作成・削除・maintenance・許可リストの変更・ジョブの提出をする | 認証した主体の権限を `runner.report` と `job.execute` の 2 つに固定する。可否は権限だけで判定する(原則 9) | T006、T024、T026、T057(FR-025) | P1 が破られた場合は防げない |
| T-R4 | **能力の偽りの申告**: ランナーが偽の能力を申告し、本来実行できないジョブ(または実行させたくないジョブ)を受け取る | 能力のキーは許可リストに載ったものに限り、リスト外のキー・型の不一致は登録ごと拒否する(既定は空 = すべて拒否。憲章 S3)。許可リストの変更は `runner.manage` の権限と監査ログを要する | T017、T018、T034、T035、T031(SC-007) | **許可リストは「送ってよい項目」を制限するだけで、申告された値の正しさは保証しない(S5)。** 値の正しさは、ランナー PC と、能力を申告する設定・ツールが信頼できることに依る(P4)。誤った能力による割り当ては、監査ログ(能力の変更前後)で追える |
| T-R5 | **機材の異常の偽りの申告**: 偽の異常の申告で割り当てを止め、ジョブの実行を妨害する | 申告はそのランナーのトークンだけが行え、申告と説明を監査ログに残す。権限を持つ主体は異常を手動で解除できる。実行中のジョブはシステムから止めない | T052、T053、T051 | 正規のランナーの侵害(P4)による妨害は防げない。気付くのは一覧(全員が閲覧できる)と監査ログ |
| T-R6 | **異常の説明を経由した持ち出し**: 異常の説明の文字列に、PC 内の情報(ファイルの内容、環境変数、資格情報)を載せて core へ送る | 説明は 1〜200 文字、改行・制御文字なしに制限する(台帳 E4)。core は中身を解釈せず、説明に載せてよい内容は 004 と台帳で定める。能力の申告も、長さ・文字・個数を制限する | T010、T008、T052 | 制限内の短い文字列による少量の持ち出しは防げない。004 の送信前の検査と、台帳 E4 の運用で補う |
| T-R7 | **生存通知・要求の大量送信**: 大量の要求で監査ログや処理を埋め、他の操作を妨げる | 状態が変わらない生存通知・割り当ての要求は監査ログに記録しない(状態の変化だけを記録)。認証の失敗の流量の制限は 003 | T049、T060 | 流量の制限は 003 の範囲。認証の失敗の記録は DENIED として残るため、大量の失敗は監査ログを増やす → 003 で制限する |
| T-R8 | **割り当ての取り違え**: 同時の要求で、1 件のジョブが 2 台に割り当てられる、maintenance・異常のランナーに割り当てられる | 割り当てとリースの作成を 1 回の UoW で確定し、`version` の衝突で判定からやり直す。ランナーの状態は時刻から導き、定期処理の遅れに左右されない | T045、T046、T042、T043(SC-002、SC-006) | 実アダプタが排他の約束を破る → 同じ契約テストを実アダプタでも実行する |

## 4. 004 ランナーエージェント(004 の plan で追記)

- 作業フォルダ外の情報の持ち出し(憲章 S1)、環境変数の継承、パスの逸脱、外部ツール自体の悪意。

## 5. 005 GitHub 連携(005 の plan で追記)

- ワークフローの権限、OIDC トークンの検証、書き戻しの項目の固定。

## 6. 実装との対応(001 の実装の完了時点。2026-11-21)

| 脅威 | 実装 | テスト |
|---|---|---|
| T-1 | `core/src/job_core/job/application/authorization.py` | `core/tests/unit/test_authorization.py`(9 権限の全部分集合 512 通り × 所有 × 状態 × 操作。主体の種類で結果が変わらないこと) |
| T-2 | `authorize_submit`、`Submitter`(`commands/submit.py`) | `test_us1_submit_and_order.py::test_edge_on_behalf_requires_permission`、`::test_edge_on_behalf_records_both_principals` |
| T-3 | `Job.finish` / `Job.confirm_stopped` の割り当て先の検査、`audit_support.audited_denials` | `test_job_transitions.py::test_report_from_other_runner_is_rejected_without_change`、`test_us1_submit_and_order.py::test_edge_report_from_unassigned_runner_is_rejected_and_audited`、`test_us3_cancel_and_abort.py::test_edge_stop_confirmation_from_unassigned_runner_is_rejected` |
| T-4 | `AuditLog` のポート(追記のみ)、`commands/purge.py`、`RetentionPolicy` | `testing/src/job_testing/contracts/audit_outbox.py::AuditLogContract`、`test_retention.py` |
| T-5 | `JobCompleted`(項目の固定)、`job_completed.v1.json` | `core/tests/contract/test_job_completed_event.py`(JSON Schema の適合、任意の payload・要約が現れないこと) |
| T-6 | `.importlinter`、依存 0 の `core/pyproject.toml` | `core/tests/architecture/test_imports.py`、`test_vocabulary.py`、`uv run lint-imports` |
| T-7 | `retry_policy.run_in_unit_of_work`、Fake の UoW の version の比較 | `contracts/persistence.py::UnitOfWorkContract`、`test_concurrency_*.py` |
| T-8 | `ops/dev/setup-dev.ps1`、`ops/dev/dev.config.psd1`、`uv.lock`、CI のワークフロー | `ops/dev/tests/setup-dev.Tests.ps1`(ハッシュの不一致で停止、許可リスト外の拒否) |

### 002 ランナー管理(実装の完了時点。2026-11-21)

| 脅威 | 実装 | テスト |
|---|---|---|
| T-R1 | `runner/domain/token.py`(`hash_token`、`hmac.compare_digest`、`repr` の秘匿)、`shared/secret_generator.py`、`commands/token.py`(再発行 = 旧の失効 + 新の発行を同じ UoW)、`commands/authenticate.py` | `unit/runner/test_token.py`、`acceptance/runner/test_token_non_exposure.py`(任意の操作の列で、値とハッシュが戻り値・監査・例外に現れない。SC-008)、`test_us7_token.py`(失効・再発行・再発行と認証の同時実行)、`testing/.../runner_persistence.py::RunnerTokenRepositoryContract`(値を保持しない) |
| T-R2 | `runner/application/authorization.py::require_self`(`RunnerIdentityMismatch` は 001 の `RunnerMismatch` の一種)、`runner/application/audit.py::audited` | `test_us7_token.py::test_us7_4_token_of_another_runner_is_rejected_for_every_runner_operation`、`test_us3_request_job.py::test_request_for_other_runner_is_rejected_and_audited` |
| T-R3 | `commands/authenticate.py`(権限を 2 つに固定)、`access/permission.py`、`runner/application/authorization.py` | `unit/runner/test_authorization.py`(12 権限 4096 通り)、`test_authenticate.py`、`test_us7_token.py::test_fr025_runner_token_cannot_do_anything_but_runner_operations` |
| T-R4 | `runner/domain/allowlist.py`(既定は空。リスト外・型の不一致・制限違反は登録ごと拒否。違反にキーと理由だけを含む)、`commands/register.py`、`commands/allowlist.py` | `unit/runner/test_allowlist.py`、`test_us1_create_and_register.py::test_us1_5_*`(SC-007)、`core/tests/contract/test_runner_requirement_schema.py`(申告の形のスキーマと検査の一致) |
| T-R5 | `commands/fault.py`(申告はそのランナーのトークンだけ。手動の解除は `runner.manage`)、`runner/domain/runner.py` | `test_us5_equipment_fault.py`(申告・回復・手動の解除・実行中のジョブを止めない) |
| T-R6 | `runner/domain/values.py::FaultDescription`(1〜200 文字、改行・制御文字なし)、値の長さ・文字・個数の制限 | `unit/runner/test_values.py`、`test_us5_equipment_fault.py::test_description_limits`、`test_allowlist.py::test_value_limits` |
| T-R7 | `runner/application/commands/heartbeat.py`(状態の変化だけを記録)、`audit.py::append_connectivity_change` | `test_us4_heartbeat_and_lease.py::test_us4_1_online_transition_is_audited_only_on_change`、`test_audit_coverage.py`。流量の制限は 003 |
| T-R8 | `commands/request_job.py`(1 回の UoW)、`job/application/commands/assign.py::assign_next_in`、`runner/domain/runner.py::state_at`(時刻から導出)、`testing/.../runner_repositories.py`(`version` の衝突と一意性) | `test_concurrency_request_job.py`、`test_us3_request_job.py`、`test_eligibility_consistency.py`(SC-001)、`RunnerUnitOfWorkContract`、`LeaseRepositoryContract` |

## 7. 改定の手続き

新しい脅威・対策を加えるときは、本書を更新し、対応するタスクとテストを書く。
対策の欄は、実装の完了時に、実際のタスクとテストに対応付ける(001 の T079)。
