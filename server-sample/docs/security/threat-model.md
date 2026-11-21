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

## 7. 改定の手続き

新しい脅威・対策を加えるときは、本書を更新し、対応するタスクとテストを書く。
対策の欄は、実装の完了時に、実際のタスクとテストに対応付ける(001 の T079)。
