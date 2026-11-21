# Implementation Plan: コア — ジョブの受付・キュー管理

**Branch**: `job_service`(spec ディレクトリ: `specs/001-core-job-queue`) | **Date**: 2026-11-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-core-job-queue/spec.md`

## Summary

外部ツールを 1 回実行する依頼(ジョブ)を受け付け、1 本の待機列で順番を管理する、用途に依存しないコアを、
**標準ライブラリだけの Python パッケージ `job_core`** として作る。HTTP・DB は扱わず、永続化・ランナーの判定・時刻・ID はポートとして定義し、
Fake で spec の受け入れシナリオをすべて検証する。

技術的な要点([research.md](research.md)):

- 待機列は、待機中のジョブの**明示的な順序付きリスト**を持つ 1 個の集約。優先度は持たず、末尾への追加・指定したジョブの前後への追加・移動だけで並びが決まる(R3)。
- 割り当て・スケジュール変更・取り消しの競合は、集約の `version` による楽観的排他と、**判定からのやり直し**で「どちらか一方だけが成立」を守る(R4)。
- 権限は 9 種の permission(spec FR-023 の 7 種 + ランナー用の `job.execute`・削除の実行用の `retention.purge`)。主体の種類では判定しない。可否は純粋な関数に集め、組み合わせを網羅してテストする(R8)。
- 終了の報告・停止の確認は、報告したランナーが割り当て先と一致するときだけ受け付け、不一致は拒否して監査ログに残す(R6)。
- 状態を変える操作は、同じ Unit of Work で監査ログとアウトボックス(ジョブ完了イベント)を確定する(R9、R10)。
- 依存規則・語彙・禁止 API・イベントの機密を、自動の検査で CI に載せる(R15)。

## Technical Context

**Language/Version**: Python 3.12 以上(R1)

**Primary Dependencies**: 実行時は標準ライブラリのみ(依存 0)。開発時: pytest、Hypothesis、pytest-cov、jsonschema(イベントの契約テスト)、import-linter、ruff、mypy。パッケージ管理は uv のワークスペース

**Storage**: N/A(リポジトリ・Unit of Work のポートのみ。実装は core-persistence で 003 と合わせて行う。R2)

**Testing**: pytest(単体・受け入れ・契約・アーキテクチャ・性能)、Hypothesis(待機列の不変条件)、Pester と PSScriptAnalyzer(開発環境の構築スクリプト)

**Target Platform**: Windows 10/11・Windows Server 上の CPython(憲章 原則 7)。core 自体は OS に依存しない

**Project Type**: ライブラリ(モノレポ内の独立パッケージ `core/`。テスト支援の `testing/` を併設)

**Performance Goals**: 待機中 500 件・ランナー 50 台で、提出の受付/拒否の判定が core 内で 50 ms 以下(SC-005 の 2 秒の内訳のうち core 分の目安。DB を含む計測は 003)

**Constraints**: 外部への送信をしない(FR-029)。core は他のモジュール・サードパーティを import しない(FR-028)。用途・プラットフォームの語を含まない(SC-009)

**Scale/Scope**: ランナー数十台、同時に待機するジョブ数百件(spec 前提)。ユースケース 8 + 問い合わせ 4、集約 2(Job、Queue)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

判定: ✅ 適合 / ➖ 本 feature の対象外(担当の feature を記す) / ⚠️ 条件付き(条件を記す)

### S. 機密情報の保護

| 項目 | 判定 | 本 feature での扱い |
|---|---|---|
| S1 持ち出し禁止 | ➖ | 対象はワーカーとワークフロー(004、005)。core は作業フォルダ・環境変数・外部ツールを扱わない |
| S2 書き出し台帳 | ✅ | core の外への出口は、ジョブ完了イベント(E10 の元データ)と結果の書き戻しのポート(E9 の元データ)だけ。spec「外部への書き出し」の表と一致。イベントの項目は JSON Schema で固定(R10)。開発環境の構築と CI による、公式の配布元と PyPI からの取得(取得のみ)は、台帳 E15 に追加し、レビュー済み(R17) |
| S3 既定は拒否 | ✅ | core は送信の手段を持たない。イベントは `additionalProperties: false` で、許可した項目以外を持てない |
| S4 担保の方法 | ✅ / ➖ | core に関わる項目: 「通知と書き戻しにログ本文・成果物の中身を含めない」→ イベントの型で担保し、property-based テストで検査(R15-5)。「製品自身がテレメトリを送らない」→ 禁止 API の検査(R15-3)。その他(環境変数、引数配列、パス検査、ACL、ファイアウォール、ワークフロー)は 004 / 005 / 009 |
| S5 多層防御と限界 | ➖ | 隔離の限界は 004 の範囲。core は外部ツールを起動しない |
| S6 脅威モデルの先行 | ⚠️ | **脅威モデルが未作成**。憲章は「最初の実装の前」に作成を求め、本 feature が最初の実装になる。**実装(/speckit-implement)の着手前に、脅威モデル(少なくとも core の信頼境界: 呼び出し元が認証済みの主体を渡す前提、権限の偽装、割り当て先でないランナーによる報告の偽装、監査ログの改ざん、イベント経由の漏洩)を作成すること**を、tasks の最初のタスクとして置く。plan と設計の段階は進めてよい |

### 中核原則

| 原則 | 判定 | 本 feature での扱い |
|---|---|---|
| 1 モジュール分割と再利用性 | ✅ | `core/` は独立パッケージ、依存は標準ライブラリのみ。import-linter と AST 検査を CI で実行(R15)。公開契約: ユースケース([contracts/application-api.md](contracts/application-api.md))、ポート([contracts/ports.md](contracts/ports.md))、イベントスキーマ(版付き)。拡張はポートの実装の差し替えのみ |
| 2 DDD(軽量版) | ✅ | 集約 Job・Queue、値オブジェクト、ドメインイベント。状態の変更は集約のメソッドのみで、不正な遷移は例外。job と access のコンテキストを分け、runner は ID 参照のみ(R5、R6) |
| 3 プラットフォーム非依存 | ✅ | プラットフォームの語を持たない(語彙検査 R15-4)。出所情報は不透明な文字列 |
| 4 作らないもの | ✅ | 1 ジョブ = 1 回の実行。パイプライン・自動トリガ・優先度の自動決定を作らない |
| 5 運用上の要件(待機列の順序の制御) | ✅ | 憲章 v2.0.0 に適合。優先度の項目・自動の並べ替えを持たない(FR-005)。順序は追加の位置(既定は末尾、`queue.schedule` があれば指定したジョブの前後)とスケジュール変更だけで決まる(R3)。突発のジョブは位置を指定した追加として扱う。位置を指定した追加・スケジュール変更・やり直し・取り消し・強制中断を、権限を持つ利用者が運用中にいつでも行え、実行中のジョブを止めない(FR-013) |
| 6 監査ログ | ✅ | 状態を変える操作をすべて同じ UoW で記録。権限による拒否と、割り当て先でないランナーからの報告の拒否も記録(R6、R9) |
| 7 実行環境 | ✅ | Windows 上の CPython。仮想化・コンテナを使わない |
| 8 ネットワーク境界 | ➖ | core はネットワークを扱わない(003、004) |
| 9 認可 | ✅ | permission 単位(R8)。ランナーの操作(`job.execute`)と保持期間による削除(`retention.purge`)も権限で判定し、主体の種類は判定に使わない。ロールとグループの対応、各主体への権限の付与は 003 / 005 |
| 10 実行対象の固定 | ✅ / ➖ | 出所情報のリビジョンを保持し、やり直しでそのまま引き継ぐ(FR-018)。形式の検査と許可リストは提出経路(005) |
| 11 テスト | ✅ | ドメインの単体テスト、状態遷移と権限の網羅、ポートの契約テストを Fake と実アダプタで共有(`job_testing.contracts`)。GitHub なしで全検証が動く(R16) |
| 12 未確定事項 | ✅ | spec の `[NEEDS CLARIFICATION]` は 0 件。plan で決めた解釈は research に明記(R8 の「判断が必要だった点」など) |
| 13 WebUI | ➖ | 006 |
| 14 環境構築の支援 | ✅ | DB・サーバーなし。開発環境の構築と検証を冪等な PowerShell スクリプト `ops/dev/setup-dev.ps1`(ドライラン・事前確認・ハッシュ検証・動作確認・撤去)で提供(R17、[quickstart.md](quickstart.md)) |

**ゲートの結果(Phase 0 前)**: 違反なし。S6 は「実装の着手前の条件」として持ち越す。→ Phase 0 へ進む。

**再評価(Phase 1 後、2026-11-21 の更新を含む)**: 設計成果物([data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md))を確認し、判定は上表のとおり。
analyze の指摘 D1(原則 5)は憲章 v2.0.0 への改定で、D2(原則 9)は権限の追加で、D3(S2・S3)は台帳 E15 で解消した。
新たな依存・用途固有の語は加えていない。残る条件は S6(T001 の脅威モデル)だけ。

## Project Structure

### Documentation (this feature)

```text
specs/001-core-job-queue/
├── spec.md
├── plan.md                              # 本書
├── research.md                          # Phase 0
├── data-model.md                        # Phase 1
├── quickstart.md                        # Phase 1(試行・検証の手順)
├── contracts/
│   ├── application-api.md               # ユースケースの入出力・拒否・権限表
│   ├── ports.md                         # ポートの約束と契約テストの一覧
│   └── job-completed-event.schema.json  # ジョブ完了イベント(JSON Schema、版 1)
├── checklists/requirements.md
└── tasks.md                             # Phase 2(/speckit-tasks で作成)
```

### Source Code (repository root)

```text
pyproject.toml                 # uv ワークスペースの定義(members: core, testing)
.importlinter                  # 依存規則の契約(R15-1)

core/                          # 配布名 job-core / import 名 job_core(実行時の依存なし)
├── pyproject.toml
├── src/job_core/
│   ├── shared/                # 識別子の型、Clock・IdGenerator のポート、例外の基底、ドメインイベントの基底
│   ├── access/                # Principal、Permission、PrincipalKind(値オブジェクトのみ)
│   └── job/
│       ├── domain/            # Job、Queue、JobDefinition ほか値オブジェクト、JobState と遷移、
│       │                      # CancellationRecord、AuditRecord、JobCompleted、RetentionPolicy、ドメインの例外
│       └── application/
│           ├── ports.py       # UnitOfWork、各リポジトリ、AuditLog、Outbox、RunnerEligibility
│           ├── authorization.py   # 可否の純粋な関数(権限表)
│           ├── commands/      # submit、reschedule、cancel、retry、assign、report_finished、confirm_stopped、purge
│           ├── queries/       # list_jobs、get_job、get_job_history、get_audit_log
│           └── retry_policy.py    # 楽観的排他の衝突時のやり直し
└── tests/
    ├── unit/                  # 集約・値オブジェクト・権限表(Hypothesis を含む)
    ├── acceptance/            # spec の受け入れシナリオとエッジケース(Fake を使用)
    ├── contract/              # イベントの JSON Schema 適合と機密の検査
    ├── architecture/          # 標準ライブラリのみ・禁止 API・語彙の検査、forbidden_terms.txt
    └── perf/                  # 500 件・50 台の目安(マーカー perf)

testing/                       # 配布名 job-testing / import 名 job_testing(core の開発時依存)
├── pyproject.toml
├── src/job_testing/
│   ├── core_fakes/            # メモリ上の UoW・リポジトリ・AuditLog・Outbox、Fake のランナー一覧、固定の時計、連番 ID、build_core()
│   └── contracts/             # ポートの契約テスト群(core-persistence・002 の実装も同じものを実行)
└── tests/                     # 契約テストを Fake に対して実行

ops/dev/                       # 開発環境の構築(原則 14。009 の ops/common ができたら寄せる)
├── setup-dev.ps1
├── dev.config.psd1
└── tests/                     # Pester
```

**Structure Decision**: inputs/12-plan のモノレポ構成のうち、本 feature では `core/`、`testing/`、`ops/dev/` だけを作る。
002(ランナー管理)は同じ `job_core` に `runner/` コンテキストとして追加し、`RunnerEligibility` の実装を提供する。
core-persistence・core-api は 003 で追加する。

## 追補(本 feature の外で行う、文書の整合の作業)

憲章 v2.0.0(2026-11-21。原則 5 の改定)は**完了**。憲章の Sync Impact Report に挙げた参照文書の食い違いを、次のとおり別途直す(R18)。
本 feature の設計・実装は改定済みの憲章に従っており、これらの修正を前提としない。

1. inputs/01-constitution: 原則 5 の入力の文言(優先度変更・割り込み・管理者)を、憲章 v2.0.0 に合わせる。
2. inputs/02-modules: コアの責務の「優先度」を「並び順」に改め、汎用モデルから `priority` を削除する。
3. inputs/12-plan: テストの「状態遷移・優先度・要件マッチング・権限」の「優先度」を「並び順」に改める。
4. inputs/13-security-egress E1: 「希望優先度」を削除する(位置の指定は `queue.schedule` を要する操作で、提出経路の契約での扱いは 005 で決める)。

## Complexity Tracking

Constitution Check に、正当化を要する違反はない。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (なし) | — | — |
