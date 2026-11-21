# Phase 0 調査: コア — ジョブの受付・キュー管理

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-21

Technical Context の未確定事項と、技術選定・設計上の判断を、次の形式でまとめる。
spec の `[NEEDS CLARIFICATION]` は 0 件(Clarifications セッション 2026-11-20 で解消済み)。
本書で扱うのは、spec が「plan で決める」としている実装上の判断だけである。

---

## R1. 言語・実行環境とパッケージ構成

- **Decision**: Python 3.12 以上。`core/` を独立パッケージ(配布名 `job-core`、import 名 `job_core`)とし、uv のワークスペースに置く。
  core の実行時依存は**標準ライブラリのみ**(依存 0)。テスト用の Fake と契約テストは `testing/`(配布名 `job-testing`、import 名 `job_testing`)に置き、core の開発時依存とする。
- **Rationale**: inputs/12-plan の共通スタックと、「core は標準ライブラリのみ」(02-modules の依存規則)に従う。
  Fake を `testing/` に分けると、core-persistence(実アダプタ)が同じ契約テストを import して流用できる(憲章 原則 11)。
- **Alternatives considered**:
  - Fake を `core/tests/` に置く: core-persistence から再利用できず、契約テストが二重になるため不採用。
  - 001 と 002 を別パッケージにする: 割り当て(FR-009)はジョブとランナーの両コンテキストにまたがり、
    02-modules でも「core(001, 002)」を 1 モジュールとしているため、パッケージは 1 つにし、コンテキストはサブパッケージで分ける。

## R2. 永続化と HTTP の扱い

- **Decision**: 本 feature は HTTP・DB を扱わない。永続化は「リポジトリ」と「Unit of Work」のポートとして定義し、
  Fake(メモリ上の実装)で全シナリオを検証する。SQLAlchemy の実装は core-persistence(003 と合わせて実施)が、同じ契約テストを通す。
- **Rationale**: inputs/12-plan「001 / 002: core パッケージのみを対象とする。HTTP・DB は扱わず、永続化はリポジトリのポートとして定義する」。
- **Alternatives considered**: 本 feature で SQLAlchemy の実装まで作る — スコープ外(12-plan の指定)のため不採用。

## R3. 待機列の並び順の表現

- **Decision**: 待機列を 1 個の集約 `Queue` とし、待機中のジョブの識別子の**明示的な順序付きリスト**と、楽観的排他のための `version` を持つ。
  ドメインでの位置は 1 始まりの整数(先頭 = 1)。永続化の表現(行ごとの順位キー等)は core-persistence が決め、
  推奨として「文字列の分数順位キー(fractional indexing)」を data-model に記す。
- **Rationale**:
  - 規模は待機中 数百件(spec 前提)。全体をメモリ上で扱っても SC-005(2 秒以内・500 件)を十分に満たす。
  - 1 本の待機列(FR-008)を 1 集約にすると、「移動以外の相対順序は変えない」(FR-011)「同時の操作はどちらか一方だけが成立」(Edge Cases)を、集約の不変条件と `version` の比較だけで守れる。
- **Alternatives considered**:
  - 整数の連番を各ジョブに持たせ、移動のたびに振り直す: 同時更新の衝突範囲が広く、不変条件がジョブ側に散るため不採用。
  - 優先度 + 提出時刻での並べ替え: spec FR-005 で優先度を廃止したため不採用。
  - 連結リスト(前後のジョブの識別子を持つ): 位置(何番目か)の算出と整合性の検査が煩雑になるため不採用。

## R4. 同時実行の制御(割り当て・スケジュール変更・取り消しの競合)

- **Decision**: 状態を変えるユースケースはすべて、1 回の Unit of Work(UoW)の中で「読み込み → 判定 → 変更 → 監査ログ・イベントの記録」を行い、
  コミット時に `Queue.version` と `Job.version` を比較する(楽観的排他)。衝突したら `ConcurrencyConflict` とし、
  アプリケーション層が**最新の状態を読み直して判定からやり直す**(既定 3 回)。
- **Rationale**:
  - Edge Cases「スケジュール変更と割り当てが同時に起きる → どちらか一方だけが成立」「権限の判定はその時点の状態で行う」を、
    判定のやり直しで自然に満たせる(割り当てが先に成立していれば、取り消しの権限だけを持つ利用者の操作は、やり直し後に権限不足で拒否される)。
  - core は DB 製品を知らないため、排他の方式はポートの契約(「version が一致しなければコミットしない」)としてだけ定め、
    DB 側の実現(`SELECT ... FOR UPDATE` 等、12-plan の SKIP LOCKED を含む)は core-persistence に任せる。
- **Alternatives considered**:
  - core 内で `threading.Lock` による悲観的ロック: 複数プロセス(008 の 2 台構成を含む)で効かないため不採用(Fake の内部実装としてのみ使う)。
  - ジョブごとの独立したロックだけにする: 並び順の不変条件が待機列全体にかかるため不十分。

## R5. ランナー要件の判定(002 との境界)

- **Decision**: 001 はランナー要件を**中身を解釈しない値**(`RunnerRequirement`)として保持し、判定はポート `RunnerEligibility` に問い合わせる。
  - `any_registered_runner_may_satisfy(requirement) -> bool`(提出時の判定 FR-002。空き状態は見ない)
  - `runner_satisfies(runner_id, requirement) -> bool`(割り当て時の判定 FR-009)
  001 の検証は Fake(能力の一覧を与える偽のランナー一覧)で行う。要件の文法・照合の純粋関数は 002 で実装する。
- **Rationale**: spec Key Entities「条件の文法と判定はランナー管理(002)が定め、コアの受付は判定結果だけを使う」。
- **Alternatives considered**: 001 で要件の文法を先に決める — 002 の spec 範囲を侵すため不採用。

## R6. 割り当てとランナーの使用中の判定(FR-009、FR-010)

- **Decision**: ユースケース `AssignNextJob(runner_id)` を用意する(呼び出しは 003 / 004 の取得要求)。
  1. その UoW の中で、そのランナーに割り当て済みで終了していないジョブがあれば、`RunnerBusy` で何も割り当てない(FR-010)。
  2. 待機列を先頭から走査し、`runner_satisfies` が真になる最初のジョブを取り出して、実行中へ遷移させる(FR-009、US1-5)。
  3. 該当がなければ「割り当てなし」を返す。
  リース(期限付きの割り当て)と再割り当ては 004 / 002 で扱い、001 は「実行中 = ランナーの識別子を持つ」までを定める。
  終了の報告(`ReportFinished`)と停止の確認(`ConfirmStopped`)は、報告したランナーの `runner_id` を受け取り、
  `Job.assigned_runner_id` と一致しなければ `RunnerMismatch` で拒否し、監査ログに `DENIED` として記録する。
  `runner_id` と呼び出し元のランナーの主体の対応は、呼び出し元(003。ランナーごとのトークン)が保証する(analyze の指摘 C1)。
- **Rationale**: ランナーの稼働状態は 002 の内部状態だが、「1 台に 2 件を割り当てない」は 001 の要件。
  ジョブ側の事実(そのランナーの識別子を持つ未終了のジョブ)だけで判定でき、他コンテキストの内部状態を参照しない(憲章 原則 2)。
- **Alternatives considered**: ランナー集約に「使用中」フラグを持たせる — 002 の未定の設計に依存するため、001 では採らない(002 で併用してもよい)。

## R7. 状態遷移と強制中断の扱い

- **Decision**: 状態は `QUEUED / RUNNING / SUCCEEDED / FAILED / CANCELLED` の 5 つ(02-modules の語)。
  強制中断は状態を増やさず、`RUNNING` のジョブに「中断の要求」(`CancellationRecord`、確定日時は未設定)を付ける。
  - 要求後、`confirm_stopped` で `CANCELLED` へ。
  - 要求後、先に `SUCCEEDED / FAILED` が報告されたら、その終了を正とし、中断の記録に「終了が先に確定した」旨を残す(Edge Cases)。
  - 終了状態からの遷移はすべて `InvalidStateTransition`(FR-021)。
  実行中の詳細な下位状態(開始の確認、リース切れ、タイムアウト)は 004 で追加する。追加は `RUNNING` の内側の拡張とし、001 の遷移表を壊さない。
- **Rationale**: spec FR-021「少なくとも 待機中 → 実行中 → 終了、待機中 → 中断。実行中の詳細は 004 と別途」。
- **Alternatives considered**: `CANCEL_REQUESTED` を独立した状態にする — 004 の下位状態と組み合わせが増え、001 の遷移表が 004 に依存するため不採用。

## R8. 権限モデル(FR-023、FR-024)

- **Decision**: 権限を列挙型 `Permission` とする。

  | 権限 | 識別子 | 用途 |
  |---|---|---|
  | ジョブ追加 | `job.submit` | 自分の名義での提出(末尾)、全ジョブのやり直し(末尾) |
  | 一般 | `job.general` | 自分のジョブの中断、全ジョブ・操作の経緯の閲覧 |
  | スケジュール変更 | `queue.schedule` | 位置を指定した追加・やり直し、待機中のジョブの移動 |
  | 取り消し | `job.cancel_queued` | 全ての待機中のジョブの取り消し |
  | 強制中断 | `job.force_abort` | 全ての実行中のジョブの強制中断 |
  | 管理 | `audit.read_all` | 監査ログ全体の閲覧 |
  | 提出代行 | `job.submit_on_behalf` | 別の提出者の名義での提出 |
  | ジョブの実行(plan で追加) | `job.execute` | 割り当ての取得、終了の報告、停止の確認(ランナー用) |
  | 保持期間による削除(plan で追加) | `retention.purge` | 保持期間による削除の実行(定期実行の主体用) |

  呼び出し元は `Principal(subject_id, permissions, kind)` を渡す(core は認証しない)。提出代行では `on_behalf_of`(名義上の提出者)を併せて渡す。
  可否の判定は、ユースケースごとの**純粋な関数**(`authorize_*`)に集め、(権限の集合 × 所有 × 対象の状態)の全組み合わせを表駆動でテストする(SC-006)。
- **判断が必要だった点**(spec の文言からの解釈):
  1. 提出代行は `job.submit_on_behalf` だけで行える(代行する主体に `job.submit` は要らない)。位置を指定する場合は `queue.schedule` も要る(spec 前提)。
  2. 「自分のジョブ」は**名義上の提出者**で判定する(spec Edge Cases)。代行した主体自身は所有者ではない。
  3. 閲覧(一覧・詳細・操作の経緯)には `job.general` を要する(FR-023 の「一般」の定義に従う)。
  4. 管理の権限は他の権限を含まない(spec 前提)。
  5. ランナーの操作と保持期間による削除も権限で判定する。`job.execute` と `retention.purge` を追加し(FR-023 は「少なくとも」次の権限を持つ、としている)、
     主体の種類(`Principal.kind`)は監査ログの表示にだけ使う。どの主体にこれらの権限を付与するかは 003(ランナーのトークン、定期実行の主体)が決める。
- **Rationale**: 憲章 原則 9(permission 単位の RBAC)。ロールとグループの対応は 003 / 005 の責務。
- **Alternatives considered**:
  - ロール名で分岐する — 原則 9・FR-023 に反するため不採用。
  - 主体の種類(`RUNNER` / `SYSTEM`)で判定する — 権限単位の判定にならず、原則 9 に反するため不採用(analyze の指摘 D2)。

## R9. 監査ログと「操作の経緯」

- **Decision**: 監査ログを追記専用のポート `AuditLog` とし、状態を変える操作の成功は、その操作と**同じ UoW** で記録する。
  権限による拒否は、本体の変更がないため、**別の UoW** で拒否の記録だけをコミットする(FR-025)。
  「操作の経緯」(FR-026)は、対象のジョブの記録のうち `outcome = SUCCEEDED` のものを時刻順に返す問い合わせとする(同じ記録の見え方を変えるだけで、別の保存先は作らない)。
  記録の種類: 提出、位置を指定した提出、やり直し、スケジュール変更、取り消し、強制中断の要求、中断の確定、割り当て、完了、保持期間による削除。
- **Rationale**: 1 つの記録源から 2 つの見え方を作ると、SC-007(100% 記録・全員が確認可能)の検証が単純になる。
- **Alternatives considered**: ジョブの集約に経緯を埋め込む — 拒否の記録や削除後の追跡(FR-032)を扱えないため不採用。

## R10. ジョブ完了イベントと取りこぼし防止(FR-027、FR-030)

- **Decision**: 集約がドメインイベント `JobCompleted` を発生させ、UoW がコミット時に**アウトボックス**(ポート `Outbox`)へ同じトランザクションで書く(トランザクショナル・アウトボックス、12-plan)。
  イベントには一意の `event_id` を付け、受け手は重複を `event_id` で除く(少なくとも 1 回の配信)。
  配信(アウトボックスからの取り出しと送信、再送)は 003 / 007 の責務とし、001 は「`pending` のイベントを取り出し、配信済みにする」ポートの操作だけを定める。
  イベントの形は JSON Schema で公開し([contracts/job-completed-event.schema.json](contracts/job-completed-event.schema.json))、
  payload・ログ本文・結果の要約の文字列を**型として持てない**(`additionalProperties: false`)。
- **Rationale**: 憲章 原則 1(イベントスキーマは公開契約)、S2・FR-030(参照用の識別子のみ)、SC-008・SC-010。
- **Alternatives considered**: コミット後にコールバックで直接通知 — コミットと送信の間の障害で失われるため不採用。

## R11. 重複の判定(FR-006)

- **Decision**: 重複の鍵は `(source_ref.source, source_ref.revision, job_type)`。`source_ref` がないジョブは判定しない。
  判定の対象は待機中のジョブだけ。`revision` がない出所情報は「リビジョンなし」という値として比較する。
  判定は待機列の UoW の中で行うため、同時の 2 件の提出も `Queue.version` の衝突で一方が判定をやり直し、重複として拒否される。
- **Rationale**: spec 前提「同じ内容 = 出所・リビジョン・ジョブの種類の一致。payload とランナー要件は見ない」。

## R12. payload・ジョブ定義の検証(FR-001、FR-003)

- **Decision**:
  - `job_type`: 空でない文字列(前後の空白を除いて 1〜128 文字)。語彙は用途側が決め、core は検査しない。
  - `requirement`: 必須。中身は検査しない(002 が定める)。
  - `payload`: 必須。JSON で表せる値(dict / list / str / 数値 / bool / null)を、深くコピーして不変にして保持する。中身は検査しない。
    サイズの上限は入口(003)で設ける。
  - `timeout`: 必須。`datetime.timedelta` で正の値(0 以下は拒否)。上限は設けない。
  - `source_ref`: 任意。`source`(1〜512 文字)と `revision`(任意、1〜256 文字)。形式(コミット識別子かどうか)は core では検査せず、提出経路(005)が憲章 原則 10 を担保する。
  - 結果の要約(`result_summary`): 1024 文字以内の文字列(任意)。超えた場合は切り詰めず拒否する(報告側 004 の不具合を隠さないため)。
- **Rationale**: payload を解釈しない(FR-001)。用途固有の値の妥当性は、用途側(プロファイル)の責務。
- **Alternatives considered**: payload を `bytes` で持つ — 003 の JSON API と相性が悪く、閲覧(US5)で扱いにくいため不採用。

## R13. 保持期間と削除(FR-031、FR-032)

- **Decision**: 設定値 `RetentionPolicy(job_retention: timedelta = 365 日, audit_retention: timedelta = 1095 日)`。
  生成時に `audit_retention >= job_retention` を検査し、満たさなければ設定エラー(FR-032)。
  ユースケース `PurgeExpired(now)` が、終了日時から期間を過ぎたジョブと、記録日時から期間を過ぎた監査ログを削除する。
  待機中・実行中のジョブは対象外。削除したジョブを `retry_of` で参照するジョブは残り、参照先の問い合わせは「削除済み」を返す。
  定期実行の仕組み(スケジューラ)は 003 / 009 の責務。時刻はポート `Clock` から得る。
- **Rationale**: core は時刻の取得と定期実行の手段を持たず、テストで時刻を固定できるようにする。

## R14. 識別子と時刻

- **Decision**: 識別子(ジョブ、監査記録、イベント)はポート `IdGenerator` で発行する文字列(既定の実装は `uuid.uuid4()` の文字列)。
  時刻はポート `Clock`(タイムゾーン付き UTC の `datetime`)。
- **Rationale**: テストでの再現性。UUIDv7 は標準ライブラリでは 3.14 からのため、既定にしない(並び順は待機列が明示的に持つので、時刻順の ID は不要)。

## R15. 自動検査(FR-028、FR-029、SC-009、SC-010)

- **Decision**:
  1. **依存の検査**: import-linter の契約(`.importlinter`)を CI で実行する。
     - `job_core` は `job_core` 以外の first-party パッケージを import しない(forbidden 契約)。
     - 層: `job_core.*.domain` → `job_core.*.application` の向きのみ(layers 契約)。
     - コンテキスト間: `job_core.job` と `job_core.access` は domain 同士で直接参照しない(access は値オブジェクトのみ公開)。
  2. **標準ライブラリのみの検査**: テストで `job_core` の全モジュールの import を AST で列挙し、`sys.stdlib_module_names` と `job_core` 以外を検出したら失敗。
  3. **禁止 API の検査**: 同じ AST 検査で、`socket`、`http`、`urllib`、`ssl`、`smtplib`、`subprocess`、`ftplib` などの外部送信・外部実行に当たる標準モジュールの import を禁止(FR-029)。
  4. **語彙検査**: 禁止語の一覧(`core/tests/architecture/forbidden_terms.txt`。GitHub・Actions・GitLab・機材・評価・用途固有のツール名など)に一致する語が、`job_core` のソース(識別子・文字列・コメント)に含まれないことをテストで確認(SC-009)。一覧はレビュー対象のファイルとする。
  5. **イベントの検査**: `JobCompleted` の直列化結果が JSON Schema を満たし、payload・結果の要約の値が文字列としても現れないことを、property-based テストで確認(SC-010)。
- **Rationale**: 憲章 原則 1(CI で依存規則)、3、S2、12-plan の「語彙検査」「禁止 API の使用検査」。

## R16. テスト方式

- **Decision**: pytest、Hypothesis(待機列の不変条件の property-based テスト)、pytest-cov。静的検査は ruff と mypy(`--strict`)。
  - ドメインの単体テスト: 状態遷移表の全組み合わせ、待機列の操作(追加・前後への追加・移動・取り出し)の不変条件
    (「重複なし」「移したジョブ以外の相対順序は不変」「位置が変わらない移動は成功で無変化」)。
  - 権限: 9 権限の部分集合(2^9 = 512 通り)× 所有(自分/他人)× 対象の状態 の表駆動テスト(SC-006)。
  - アプリケーションの受け入れテスト: spec の受け入れシナリオ(US1〜US6)とエッジケースを 1 対 1 でテストにする。
  - 契約テスト: `job_testing.contracts` にポートごとのテスト群を置き、Fake で実行する(core-persistence も同じものを実行する)。
  - 同時実行: Fake の UoW に「コミット直前に別の操作を割り込ませる」フックを用意し、競合のシナリオ(Edge Cases)を決定的に再現する。
  - 性能: 待機中 500 件・ランナー 50 台の Fake で、提出の判定が 2 秒を大きく下回ること(目安 50 ms 以下)を確認する(SC-005 の core 部分。DB を含む計測は 003)。
- **Rationale**: 憲章 原則 11(ドメイン層の単体テスト必須、状態遷移と権限の網羅、契約テストを Fake と実アダプタで共有)。

## R17. 環境構築の支援(憲章 原則 14)

- **Decision**: 001 は DB・サーバーを持たないため、マイグレーションはない。試行は「開発環境の構築 + テストの実行」とし、
  冪等な PowerShell スクリプト `ops/dev/setup-dev.ps1` を用意する。
  - 事前確認(PowerShell の版、Python 3.12 以上の有無)、`-WhatIf` によるドライラン、uv の導入(公式の配布元から版を固定し、SHA-256 を検証)、
    `uv sync --locked`(`uv.lock` のハッシュで検証。ロックと食い違えば停止)、動作確認(`uv run pytest core` と import-linter)、撤去(`-Uninstall` で `.venv` とキャッシュを削除)。
  - 取得先は、各ツールの公式の配布元と、公式のパッケージ索引(PyPI)に限る(取得のみ)。書き出し台帳の E15 に載せた(CI のワークフローも同じ)。
  - 設定値(uv の版とハッシュ、配布元の URL)は `ops/dev/dev.config.psd1` に置く。秘密情報は使わない。
  - Pester で冪等性とドライランを検査し、PSScriptAnalyzer を通す。
  009 の共通部品(`ops/common/`)ができたら、それへ寄せる。
- **Rationale**: 原則 14「各 feature の試行の前に、必要な構築をスクリプトで再現できる」。
- **Alternatives considered**: 手順書だけにする — 原則 14 に反するため不採用。

## R18. 憲章 原則 5 との整合(優先度の廃止)

- **Finding**: 憲章 v1.0.0 の原則 5 は「待機中ジョブの**優先度変更**・順序入れ替え、突発のジョブの**割り込み**…を**管理者が**行える」としていた。
  spec(2026-11-20 の見直し)は優先度を廃止し(FR-005)、「指定したジョブの前後への追加・移動」と「スケジュール変更の権限」に置き換えた。
  当初の plan は「目的は満たすので違反ではない」と解釈したが、analyze(指摘 D1)で、憲章の文言を解釈で読み替えることは認められないとされた。
- **Decision**: 憲章を **v2.0.0(MAJOR)** に改定した(2026-11-21)。原則 5 は、優先度の概念を持たないこと、順序は追加の位置とスケジュール変更だけで決まること、
  突発のジョブは位置を指定した追加として扱うこと、操作の主体は権限を持つ利用者であることを定める。本 feature の設計はこれに適合する。
  参照文書(inputs/01-constitution、02-modules、12-plan、13-security-egress E1)の食い違いは、plan の「追補」で別途直す。
- **Rationale**: 憲章は他のすべての文書に優先し、spec と食い違う場合は、憲章を正式に改定するか spec を直す必要がある。
  優先度の廃止は spec の見直しの結論であり、利用者同士の相談で順番を決める運用(spec 背景)に合うため、憲章を改定した。
- **Alternatives considered**: spec に優先度を戻す — 2026-11-20 の見直し(相談の結果を位置で反映する)と矛盾するため不採用。
