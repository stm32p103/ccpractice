# Implementation Plan: コア — ランナーとジョブの割り当ての管理(最小版)

**Branch**: `job_service`(spec ディレクトリ: `specs/002-runner-management`) | **Date**: 2026-11-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-runner-management/spec.md`

## Summary

ランナーの作成・起動時の登録(能力の自己申告)・状態・機材の異常・トークンと、ジョブの割り当て(リース)を、
001 と同じ**標準ライブラリだけの Python パッケージ `job_core`** に、コンテキスト `job_core.runner` として加える。HTTP・DB は扱わず、Fake で spec の受け入れシナリオをすべて検証する。

技術的な要点([research.md](research.md)):

- 要件は `{"all": [条件...]}` の JSON。比較は 5 種類(一致・いずれかに一致・数値・版・包含)。能力の値は 1 つの値か集合。判定と割り当ては**同じ純粋関数**で照合する(R2、R3)。
- 割り当て・リースの作成を 1 回の UoW で確定する `RequestJob` を 002 に置き、001 の割り当ての本体を関数として切り出して再利用する(R4、R5)。
- ランナーの状態は保存せず、時刻と設定(maintenance・異常・最終応答)から導く。定期処理は監査の記録だけを担い、割り当ての正しさは定期処理に依存しない(R6、R8)。
- トークンは 256 ビットの乱数を SHA-256 で保存し、認証した主体は `{runner.report, job.execute}` だけを持つ(R9、R10)。
- 申告できる能力のキーは許可リストに限り、既定は空(すべて拒否)(R12。憲章 S3、台帳 E4)。

## Technical Context

**Language/Version**: Python 3.12 以上(001 R1)

**Primary Dependencies**: 実行時は標準ライブラリのみ(`secrets`、`hashlib`、`hmac`、`decimal` を追加で使う)。開発時は 001 と同じ(pytest、Hypothesis、pytest-cov、jsonschema、import-linter、ruff、mypy)。新しい依存なし

**Storage**: N/A(リポジトリ・Unit of Work のポートのみ。実装は core-persistence で 003 と合わせて行う)

**Testing**: pytest(単体・受け入れ・契約・アーキテクチャ・性能)、Hypothesis(照合の性質、判定と割り当ての一致)

**Target Platform**: Windows 10/11・Windows Server 上の CPython(憲章 原則 7)。core 自体は OS に依存しない

**Project Type**: ライブラリ(既存の `core/` に `runner/` を追加。`testing/` に Fake と契約テストを追加)

**Performance Goals**: 待機中 500 件・ランナー 50 台で、`RequestJob` が core 内で 50 ms 以下(SC-003 の core 分の目安。R11)

**Constraints**: 外部への送信をしない(FR-031)。`job` は `runner` を import しない。用途・プラットフォームの語を含まない(SC-012)。トークンの値を保存・表示しない(FR-022、SC-008)

**Scale/Scope**: ランナー数十台、待機中のジョブ数百件。ユースケース 15 + 問い合わせ 3、集約 4(Runner、CapabilityAllowlist、Lease、RunnerToken)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

判定: ✅ 適合 / ➖ 本 feature の対象外(担当の feature を記す) / ⚠️ 条件付き(条件を記す)

### S. 機密情報の保護

| 項目 | 判定 | 本 feature での扱い |
|---|---|---|
| S1 持ち出し禁止 | ➖ | 対象はワーカーとワークフロー(004、005)。core は作業フォルダ・環境変数を扱わない |
| S2 書き出し台帳 | ✅ | ランナー → コアの情報(登録の能力、生存通知、機材の異常と回復)は台帳 E4、コア → ランナーの応答(ジョブ定義、リースの期限、生存通知の間隔、ランナーの状態)は台帳 E16 に載せた(2026-11-21 に追記)。core 自身は送信しない |
| S3 既定は拒否 | ✅ | 能力のキーの許可リストは既定が空で、リスト外・型の不一致を含む申告は登録ごと拒否(R12)。トークンの主体は 2 権限に固定(R9) |
| S4 担保の方法 | ✅ / ➖ | core に関わる項目: テレメトリなし(禁止 API の検査、R15)。トークンの非露出を property-based テストで検査(R15-4)。その他は 004 / 005 / 009 |
| S5 多層防御と限界 | ⚠️ | 許可リストは「送ってよい項目」を制限するが、申告された値の正しさは保証しない。これを残るリスクとして脅威モデルに明記する(R18) |
| S6 脅威モデルの先行 | ⚠️ | `docs/security/threat-model.md` に 002 の節がない。**実装(/speckit-implement)の着手前に、ランナー管理の節(R18 の項目)を追記すること**を tasks の最初のタスクとして置く。plan と設計の段階は進めてよい |

### 中核原則

| 原則 | 判定 | 本 feature での扱い |
|---|---|---|
| 1 モジュール分割と再利用性 | ✅ | core の中のコンテキストとして追加し、`runner → job` の一方向。import-linter の契約を追加(R15)。公開契約: ユースケース([contracts/application-api.md](contracts/application-api.md))、ポート([contracts/ports.md](contracts/ports.md))、要件と能力の申告の JSON Schema(版付き) |
| 2 DDD(軽量版) | ✅ | 集約 Runner・CapabilityAllowlist・Lease・RunnerToken。状態の変更は集約のメソッドのみ。job の内部状態は 001 のリポジトリとユースケースの関数を通してだけ扱う(R4) |
| 3 プラットフォーム非依存 | ✅ | 能力のキーと値は不透明な文字列。語彙検査を runner にも適用(R15) |
| 4 作らないもの | ✅ | 自動検出・能力の自動取得・故障の自動検知・PC の自動プロビジョニングを作らない(spec のスコープ外) |
| 5 運用上の要件 | ✅ | 割り当ては 001 の待機列の順序だけに従い、ランナー側で順序を変えない。maintenance・異常の申告は実行中のジョブを止めない |
| 6 監査ログ | ✅ | 作成・登録・状態の変化(自動を含む)・削除・トークン・許可リスト・リース切れ・拒否を記録(R14)。生存通知そのものは状態の変化がない限り記録しない |
| 7 実行環境 | ✅ | Windows 上の CPython |
| 8 ネットワーク境界 | ✅ | 割り当て・延長は、ランナーからの要求への応答としてだけ返す(着信接続なし。FR-031)。HTTP は 003 |
| 9 認可 | ✅ | permission 単位。`runner.manage`・`runner.report`・`runner.sweep` を追加(R10)。主体の種類では判定しない |
| 10 実行対象の固定 | ➖ | 005 / 004 |
| 11 テスト | ✅ | 照合・状態の導出・リースの遷移の単体テスト、権限の網羅(4096 通り)、ポートの契約テストを Fake と実アダプタで共有。001 の `RunnerEligibilityContract` を 002 の実装でも通す(R16) |
| 12 未確定事項 | ✅ | spec の `[NEEDS CLARIFICATION]` は 0 件。既定値(30 秒・90 秒・3 分)と解釈は research に明記 |
| 13 WebUI | ➖ | 006 |
| 14 環境構築の支援 | ✅ | 001 の `setup-dev.ps1` をそのまま使い、検証の一覧に V12〜V18 を加える(R17、[quickstart.md](quickstart.md)) |

**ゲートの結果(Phase 0 前)**: 違反なし。S5・S6 は「実装の着手前の条件(脅威モデルの追記)」として持ち越す。→ Phase 0 へ進む。

**再評価(Phase 1 後)**: 設計成果物([data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md))を確認し、判定は上表のとおり。
新たな依存・用途固有の語は加えていない。001 への変更(下記)は、001 の公開契約と受け入れテストを壊さない。残る条件は S5・S6(脅威モデルの追記)だけ。

## Project Structure

### Documentation (this feature)

```text
specs/002-runner-management/
├── spec.md
├── plan.md                                    # 本書
├── research.md                                # Phase 0
├── data-model.md                              # Phase 1
├── quickstart.md                              # Phase 1(試行・検証の手順)
├── contracts/
│   ├── application-api.md                     # ユースケースの入出力・拒否・権限
│   ├── ports.md                               # ポートの約束と契約テストの一覧
│   ├── runner-requirement.schema.json         # ランナー要件(JSON Schema、版 1)
│   └── capability-declaration.schema.json     # 能力の申告(JSON Schema、版 1)
├── checklists/requirements.md
└── tasks.md                                   # Phase 2(/speckit-tasks で作成)
```

### Source Code (repository root)

```text
.importlinter                  # 契約を追加: runner-layers、job-independent-of-runner

core/src/job_core/
├── shared/
│   └── ports.py               # SecretGenerator を追加
├── access/
│   └── permission.py          # runner.manage、runner.report、runner.sweep を追加
├── job/                       # 001(下記「001 への変更」だけを行う)
└── runner/                    # 新規
    ├── domain/
    │   ├── values.py          # CapabilityKey、CapabilityValue、Capabilities、FaultDescription、RunnerTimingPolicy
    │   ├── matching.py        # parse_requirement、satisfies(純粋関数。R2、R3)
    │   ├── runner.py          # Runner、RunnerState、state_at
    │   ├── allowlist.py       # CapabilityAllowlist、ValueKind
    │   ├── lease.py           # Lease、LeaseStatus
    │   ├── token.py           # RunnerToken、ハッシュ(hashlib、hmac)
    │   └── errors.py
    └── application/
        ├── ports.py           # RunnerUnitOfWork、各リポジトリ、RunnerCatalog
        ├── authorization.py   # 可否の純粋な関数
        ├── eligibility.py     # RunnerEligibilityService(001 の RunnerEligibility の実装)
        ├── commands/          # create、register、heartbeat、request_job、fault、maintenance、delete、token、allowlist、sweep、authenticate
        └── queries/           # list_runners、get_runner、get_allowlist

core/tests/
├── unit/runner/               # 照合(Hypothesis を含む)、状態の導出、リース、許可リスト、トークン
├── acceptance/runner/         # US1〜US7、エッジケース、同時実行、判定と割り当ての一致
├── contract/                  # 要件・申告の JSON Schema と照合の実装の一致
├── architecture/              # 001 の検査が runner も対象にする(追加の作業は契約の追加だけ)
└── perf/                      # RequestJob の目安

testing/src/job_testing/
├── core_fakes/                # Runner・Lease・Token・Allowlist のメモリ上のリポジトリ、決定的な SecretGenerator、build_core() の拡張
└── contracts/                 # 002 のポートの契約テスト群

ops/dev/                       # 001 のまま。setup-dev.ps1 の -VerifyOnly に V12〜V18 を追加
```

**Structure Decision**: 001 plan の決定どおり、同じ `job_core` に `runner/` コンテキストを追加する。新しいパッケージは作らない。
core-persistence・core-api は 003 で追加する。ランナープロトコル(`runner-protocol/`)は 004 で、本 feature のユースケースの入出力に対応させる。

### 001 への変更(本 feature のタスクに含める)

001 の公開の振る舞いと受け入れテストを変えない、小さな変更に限る。

1. `job.application.commands.assign`: 本体を `assign_next_in(uow, deps, principal, runner_id, satisfies)` として切り出す。`AssignNextJob` はそれを呼ぶだけにする(R4)。
2. `job.domain.audit`: `AuditRecord.runner_id`(既定 `None`)と、`AuditOperation`・`Denial.code` の値を追加する(R14)。`AuditLog.query` の条件に `runner_id` を加える。
3. `access.permission`: 権限を 3 種追加する(R10)。001 の権限の網羅テストは 12 種(4096 通り)に広がる。
4. `job.application.commands.submit`(と `retry`): `RunnerEligibility` が送出する `InvalidRequirement` を `ValidationFailed("requirement", ...)` として拒否する(US2-5)。
5. `job_testing.core_fakes`: `FakeRunnerEligibility` は 001 のテスト用に残し、`build_core()` の既定を 002 の `RunnerEligibilityService` に切り替える選択肢を加える。001 の受け入れテストで使う要件の形(`{"キー": "値"}`)は Fake 用のまま変えない。

### 他の feature への引き継ぎ

- **003(core-api)**: SC-003(割り当ての応答 2 秒以内、95%)は API を含む値のため、003 の plan で検証する(本 feature は core 内の 50 ms の目安まで)。ランナーからの要求ごとに `AuthenticateRunner` を呼ぶ。ランナーに公開するのは `RequestJob` で、001 の `AssignNextJob` は公開しない。`SweepRunners` を 15 秒ごとに呼ぶ(`runner.sweep` の主体)。認証の失敗の流量の制限。
- **004(runner-agent)**: 起動時の `RegisterRunner`、`heartbeat_interval` ごとの `Heartbeat`、PC 内のツールからの異常と回復を受ける経路、リース切れのジョブの扱い。
- **009(環境構築)**: ランナーの作成とトークンの PC への設定の手順(12-plan の「1 回限りの登録コード」を採るかを含む)。

## Complexity Tracking

Constitution Check に、正当化を要する違反はない。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (なし) | — | — |
