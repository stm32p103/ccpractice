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

## 3B. 脅威と対策(003 コア API)

**根拠**: 憲章 S1〜S6、書き出し台帳 E4・E15・E16、003 の spec / research R4〜R12・R16・R18。
003 は、コアを HTTP で公開する入口であり、人間・サービス・ランナーの 3 種類の主体の本人性を確認する。伝送の保護(P6)、認証基盤の実装(005)、サービスの配置と ACL(009)は、本 feature の外にある。

**誰を信頼するか(003 の追加の前提)**

| # | 前提 | 担当 |
|---|---|---|
| P8 | API サーバーはイントラネット内にあり、到達できる範囲はネットワーク(ファイアウォール、`allowed_networks`)で絞られる。インターネットには公開しない | 009、003 |
| P9 | 認証基盤(`IdentityProvider` の実装)は、確認した本人性と所属グループを正しく返す。その実装は組織の認証基盤に依る | 005 |
| P10 | アクセス設定(対応表)と `server.toml` のファイルは、管理者だけが書き換えられる(ACL) | 009 |
| P11 | API サーバーのプロセスは 1 つである(通知の仲介と定期処理がプロセス内にあるため) | 003、008 |

| # | 脅威 | 対策 | 担保するタスク・テスト | 残るリスク |
|---|---|---|---|---|
| T-A1 | **認証情報の漏えい**: ログ・監査・エラー・応答・DB に値が残る | ハッシュ(SHA-256)だけを保存し、値は発行時の 1 度だけ返す。アクセスログに `Authorization`・Cookie・クエリ・本文を出さない。`repr` の秘匿 | T010、T016、T019、T033、T065、T076 | 発行の応答を受け取った側の保管は、利用者・サービスの運用に依る |
| T-A2 | **失効の遅れ**: 失効した認証情報が使い続けられる | 呼び出しごとの照合(キャッシュなし)。SSE は 15 秒ごとに認証と権限を再確認する | T017、T041、T055(SC-004) | SSE の購読では、失効から最大 15 秒の遅れがある |
| T-A3 | **権限の昇格**: サービス用の認証情報に過大な権限を付ける、人間のロールに実行用の権限を載せる、一般の利用者が代理提出する | サービス用の権限の上限、ロールに載せられない権限の設定検証、代理提出は `job.submit_on_behalf` のみ(コアが判定) | T011、T032、T033、T095(SC-003、SC-005) | 設定の上限そのものが過大な場合は防げない(P10) |
| T-A4 | **ランナーによる越権**: 他のランナーの操作、利用者向けの操作 | ランナーの識別子を URL に含めず、認証した主体から取る。ランナーの権限は 2 つに固定する(002 T-R3) | T036、T038(SC-004) | ランナーの正規のトークンを持つ者の操作は区別できない(002 T-R2) |
| T-A5 | **CSRF・オープンリダイレクト・セッションの固定** | Cookie は `__Host-session`・`HttpOnly`・`SameSite=Strict`。Cookie での状態変更は `Origin` を検査。`return_to` は同一オリジンの相対パスだけ。ログインのたびに新しいセッションの値を発行 | T020、T040、T045 | `Secure` を外した構成(HTTP)では、盗聴が成立する。P6・P8 に依る |
| T-A6 | **イントラネット外からの到達** | bind するアドレス、`allowed_networks`(認証より前に拒否)、ファイアウォール | T019、T021、T103 | 接続元の許可リストは接続のアドレスだけを見る。プロキシ構成では、プロキシのアドレスを許可する運用になり、接続元の絞り込みが弱まる |
| T-A7 | **認証失敗の洪水**: 総当たり、監査ログの水増し | 値が 256 ビットの乱数で、総当たりが成立しない。失敗の記録は、同じ接続元・同じ種類を窓(既定 1 分)ごとに 2 件以内に抑える | T016、T017 | 窓の内の失敗の個別の記録は残らない(件数だけ) |
| T-A8 | **エラー・イベント経由の情報の持ち出し・漏えい**: payload、ログ、異常の説明、能力の値、他人の情報 | エラーは写像の表だけを通す(例外の文字列を出さない)。イベントに自由な文字列を含めず、項目をスキーマで固定する | T018、T056、T063、T065、T066 | 識別子(ジョブ ID など)は通知に載る。閲覧権限(`job.general`)を持つ主体にだけ配信する |
| T-A9 | **偽の認証基盤の混入**: 試験用の実装が本番で有効になる | `profile != "dev"` では、Fake の認証基盤・メモリ上のリポジトリ・環境変数の `SecretSource` の選択を拒否する。Fake は `testing` に置き、本番のパッケージに含めない | T087、T096 | 設定ファイルの `profile` の書き換えは防げない(P10) |
| T-A10 | **対応表の改ざん・誤設定** | 変更は明示の再読み込みだけ。検証してから差し替え、失敗なら現在の対応表を保つ。差分を監査ログに残す(`ACCESS_CONFIG_CHANGE`) | T011、T042、T046 | ファイルの ACL(P10)が破られた場合は防げない。所属グループの変更は、次のログインまで反映されない |
| T-A11 | **SSE の資源の枯渇** | 接続数の上限(200)、購読者ごとの送信待ちの上限、遅い購読者の切断、認証の再確認 | T054、T055、T057 | 上限の範囲内の正規の接続による占有は防げない |
| T-A12 | **外部への書き出しの混入**: テレメトリ、認証基盤アダプタの無断の送信 | `httpx`・`requests`・`socket` などの直接の利用を検査で禁止。偽のサーバーで外向きの通信 0 件を検証。アダプタの出力先は台帳に追加してレビューを受ける(憲章 S2) | T092、T093(SC-009) | 実アダプタ(005)の通信は、005 の台帳のレビューに依る |

**残るリスク(003 全体)**

1. **所属グループの反映の遅れ**: セッションはログイン時の所属グループを保持する。認証基盤での所属の変更は、次のログイン(セッションの期限は絶対 12 時間・無操作 2 時間)まで反映されない。管理者による一括の失効で即時に切れる。
2. **接続元の許可リストの限界**: 接続のアドレスだけを見る(T-A6)。
3. **プロセスが 1 つであることへの依存**: 通知の仲介(リングバッファ)と定期処理がプロセス内にある(P11)。複数のプロセスでは、通知の取りこぼしと定期処理の重複が起きる。

「実装との対応」の表は、003 の実装の完了時点で、6 節に追記する(T097)。

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

### 003 コア API(実装の完了時点。2026-11-22。本番の認証基盤(005)は未接続)

| 脅威 | 実装 | テスト |
|---|---|---|
| T-A1 | `access/secrets.py`(SHA-256、`hmac.compare_digest`)、`access/models.py`(`repr` の秘匿)、`access/credentials.py`(値は発行の応答だけ。監査は権限の一覧と識別子だけ)、`http/middleware.py`(アクセスログに `Authorization`・Cookie・クエリ・本文を出さない)、`http/errors.py`(例外の文字列を出さない)、`core-server/__main__.py`(uvicorn のアクセスログを無効化) | `unit/test_secrets.py`、`unit/test_access_models.py`、`unit/test_service_credentials.py`(Hypothesis: 値・ハッシュが監査・一覧に現れない)、`unit/test_middleware.py`、`acceptance/test_logging.py`、`contract/test_problem_disclosure.py`(Hypothesis) |
| T-A2 | `access/authenticate.py`(呼び出しごとの照合。キャッシュなし)、`events/sse.py`(15 秒ごとに認証と `job.general` を再確認。無操作の期限は延長しない) | `unit/test_authenticate.py::test_revocation_takes_effect_on_the_next_call`、`acceptance/test_us2_*.py`・`test_us3_*.py`(失効の即時性)、`acceptance/test_events.py::test_us6_3_*`、`test_idle_timeout_is_not_extended_by_an_open_stream` |
| T-A3 | `access/config.py`(ロールに載せられない権限・サービスの上限の検証)、`access/credentials.py`(上限の部分集合)、`access/authenticate.py`(現在の上限との共通部分だけを有効)、コアの `authorize_submit`(代理提出は `job.submit_on_behalf`) | `unit/test_access_config.py`、`unit/test_service_credentials.py`、`unit/test_authn_authz.py`(2^6 の権限 × 人間・サービス × 9 操作)、`acceptance/test_us2_service_delegation.py` |
| T-A4 | `http/routers/runner_protocol.py`(ランナーの識別子を URL に含めず、認証した主体から取る)、`access/authenticate.py`(`AuthenticateRunner`。権限は 2 つに固定) | `acceptance/test_us3_runner_protocol.py`(URL に識別子がない、別のランナーの報告は `runner_mismatch`、利用者向けの操作は `403`) |
| T-A5 | `http/routers/auth.py`(`__Host-session`・HttpOnly・SameSite=Strict、`return_to` の検査、ログインのたびに新しい値)、`http/authn.py`(Cookie の状態変更は `Origin` を検査) | `acceptance/test_us4_login_and_roles.py`、`unit/test_authn_dependency.py` |
| T-A6 | `settings.py::network_allowed`、`http/middleware.py`(認証より前に `403 network_not_allowed`。`X-Forwarded-For` を信用しない) | `unit/test_settings.py`、`unit/test_middleware.py`、`acceptance/test_skeleton.py`。サーバーの bind・ファイアウォールは 009 |
| T-A7 | `access/audit.py::AuthFailureAuditor`(窓ごとに最初の 1 件と件数つきの 1 件だけ)、`scheduler.py`(窓の確定) | `unit/test_auth_audit.py`(洪水で窓ごとに 2 件以内)、`unit/test_scheduler.py` |
| T-A8 | `http/errors.py`(写像の表だけ。`detail` は固定の文面。検証エラーは位置と種類だけ)、`events/ports.py::PendingChange`(自由な文字列の項目がない型)、`events/sse.py::event_json` | `contract/test_problem.py`、`contract/test_problem_disclosure.py`、`contract/test_change_event_schema.py`、`acceptance/test_events.py::test_events_carry_no_free_text`、`testing/.../change_broker.py` |
| T-A9 | `core-server/settings.py`(`profile != "dev"` で Fake・メモリを拒否。環境変数の `SecretSource` は警告)、`core-server/wiring.py`(試験用の実装は dev のときだけ import) | `core-server/tests/test_settings.py`、`test_profile_guard.py` |
| T-A10 | `access/config.py`(検証してから差し替え)、`access/config_reload.py`(失敗で現在の対応表を保つ。差分を監査) | `acceptance/test_us4_login_and_roles.py::test_us4_2_*`、`unit/test_access_config*.py` |
| T-A11 | `settings.py`(接続数 200・送信待ち 100)、`events/broker.py`(`publish` はブロックしない。遅い購読者を切断)、`events/sse.py::SseConnections` | `unit/test_broker_contract.py`(`ChangeBrokerContract`)、`acceptance/test_events.py::test_connection_limit_*`、`perf/test_api_perf.py` |
| T-A12 | `tests/architecture/test_forbidden_apis.py`(通信 API の直接の利用を禁止)、`app.py::TELEMETRY_DISABLED`(**FastAPI の組み込みのテレメトリは、環境変数 `FASTAPI_OTEL_AUTO_CONFIGURE` で外部へ書き出せ、検証エラーの入力値や例外の内容も載りうるため、すべて無効にする**) | `acceptance/test_egress.py`(外向きの接続 0 件、テレメトリの無効化)、`architecture/test_forbidden_apis.py`、`architecture/test_vocabulary.py` |

**実装の完了時点で確認した、残るリスクの追加**: FastAPI などの依存のライブラリが、将来の版で外部への通信(テレメトリなど)を既定で有効にする可能性がある。`uv.lock` で版を固定し、版を上げるときに `test_egress.py`(外向きの接続の検知)を通すことで検出する。

## 7. 改定の手続き

新しい脅威・対策を加えるときは、本書を更新し、対応するタスクとテストを書く。
対策の欄は、実装の完了時に、実際のタスクとテストに対応付ける(001 の T079)。
