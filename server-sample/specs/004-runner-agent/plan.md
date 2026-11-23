# Implementation Plan: ランナーエージェント — 外部ツールの実行

**Branch**: `job_service`(spec ディレクトリ: `specs/004-runner-agent`) | **Date**: 2026-11-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-runner-agent/spec.md`

## Summary

各 Windows PC に常駐し、コア API からジョブを問い合わせで取得して、外部ツールとして実行し、結果を報告するエージェントを作る。
用途を知らず、**エグゼキュータ**(ジョブの payload を解釈して「実行計画」を返す部品)を、設定の対応表(ジョブ種別 → エグゼキュータ)で差し替える。
最重要の要件は機密の保護(憲章 S1〜S6)で、**エージェントが起動の条件(環境・パス・ツール・取得資格)をすべて握り、エグゼキュータにはプロセスを起動させない**設計にする。

技術上の要点([research.md](research.md)):

- パッケージは `runner-protocol`(共有スキーマ)、`runner-agent`(本体。`job_core*` を import しない)、`profile-equipment-check`(最初の用途)、`runner-service`(組み立てと起動の入口)。エグゼキュータの選択は、コード内の対応表と設定で行い、動的な読み込みを作らない(R1)。
- 外部ツールは、エージェントとは**別の低権限のアカウント**で、**空から組み立てた環境**と**引数の配列**で起動し、**Job Object** で子孫ごと停止する。作業フォルダはジョブごとに新規に作り、終了で削除する(R4、R5、R7、R8)。
- ツールの起動は**設定の登録簿(`tool_id`)**だけ。payload から実行ファイルを選べない。パスは `WorkPath` の検査(`..`、絶対、UNC、デバイス名、代替ストリーム、シンボリックリンク、ジャンクション)を通す(R7)。
- ログは、マスク(完全一致 + パターン)・量の制限を経て、`seq` つきのチャンクで逐次送る。途絶の間は状態フォルダに待避する(R10)。
- 成果物の本体はコアを通さず、**ランナー自身の PC の共有フォルダ(UNC)** または大容量ストレージ(URL)へ置き、参照だけを報告する(R11。Q2)。既定は `disabled`。
- ソースの取得はエージェントが行い、短命の取得資格はエグゼキュータに渡さない(R12。Q3)。リース切れのジョブは失敗として確定し、自動の再実行はしない(R14。Q1)。
- 待ち受けは短い間隔の問い合わせ(long polling を採らない)。中断の指示は、生存通知の応答の `abort_requested` で受ける(R3、R6)。
- 結果の報告は、ジャーナルで確定まで失われない(R13)。サービスは WinSW(R16)。
- 001〜003 への小さな追加: 権限 `job.read_output`、ログ・成果物の参照の保存と参照、`HeartbeatResult.abort_requested`、リース切れでの失敗の確定、`ReportFinished` の拡張、`SourceCredentialIssuer`(下)。

## Technical Context

**Language/Version**: Python 3.12 以上(001 R1)

**Primary Dependencies**:
- 実行時: `httpx`(`runner-agent`)。TOML は標準ライブラリ(`tomllib`)。Windows の機能(Job Object、ログオン付きのプロセス生成、資格情報の保管機能、リパースポイント)は `ctypes` で呼ぶ(追加の依存なし)
- `core` 側の追加(`core-api`・`core-persistence`): 003 と同じ(FastAPI、SQLAlchemy など)
- 開発時: 001〜003 と同じ(pytest、Hypothesis、pytest-cov、jsonschema、import-linter、ruff、mypy、httpx、schemathesis)
- 版は `uv.lock` で固定する。取得は公式の索引(PyPI)だけ(台帳 E15)

**Storage**: エージェント: 状態フォルダのファイル(ジャーナル、ログの待避、監査)。コア: PostgreSQL にログ・成果物の参照の表を追加(core-persistence)

**Testing**: pytest(単体・受け入れ・契約・アーキテクチャ)、Hypothesis(パスの検査、マスク、payload)。契約テストは Fake と実アダプタの両方(憲章 原則 11)。Windows の OS 機能は `-m windows`、2 アカウントは `-m twoaccount`(既定では実行しない)

**Target Platform**: Windows 10/11・Windows Server 上の CPython(憲章 原則 7)。ランナー PC のみ。ランナーからサーバーへの接続のみ(原則 8)

**Project Type**: 常駐のサービス(ライブラリ 3 + 起動の入口 1。`runner-protocol`、`runner-agent`、`profile-equipment-check`、`runner-service`)

**Performance Goals**: ログがコアに届くまで 1〜2 秒(SC なし。運用上の目安)。中断の指示を受けてから停止まで 10 秒以内(SC-005)。待機中の問い合わせの負荷は 1 台あたり 0.2 件/秒

**Constraints**: 外向きの通信は、コア API・ソース取得先・成果物の保存先だけ(台帳 E4〜E7)。同時に実行するジョブは 1 件。外部ツールに親の環境を継承しない。秘密(トークン、取得資格、ツールのアカウントの資格)を、ログ・監査・例外・状態に出さない。用途固有の語・GitHub の語をエージェント本体に含めない

**Scale/Scope**: ランナー数十台(001 の想定)。ログは 1 ジョブ 10 MiB まで(既定)。成果物は 1 ジョブ 100 件・合計 4 GiB まで(既定)。エンドポイントの追加は 5 つ(ランナー向け 3、利用者向け 2)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

判定: ✅ 適合 / ➖ 本 feature の対象外(担当の feature を記す) / ⚠️ 条件付き(条件を記す)

### S. 機密情報の保護

| 項目 | 判定 | 本 feature での扱い |
|---|---|---|
| S1 持ち出し禁止 | ✅ | 外部ツールは別のアカウントで、作業フォルダだけに権限を持つ(R4)。作業フォルダはジョブごとに新規・終了で削除(R5)。作業フォルダ外のファイル・環境変数・他のサービスの情報は、ログ・成果物・コアへの通信に現れないことを、ダミーの秘密で検査する(V6) |
| S2 書き出し台帳 | ✅ | 書き出しは E4〜E7(E6 を含む)の範囲。次の改定を、2026-11-22 に台帳へ反映した(承認済み): (1) **E16**: コア API からランナーへの応答に、「ジョブごとの短命の取得資格(`source-credential` の応答)」と「中断の指示(`abort_requested`)」を加える。(2) **E4**: ジョブの状態に、`failure_reason`(固定の語彙)・`counters`(件数だけ)・`exit_code` を含める。(3) **E7**: 取得資格が、コア API 経由で渡ることを明記する。(4) **E6 の宛先**: ランナーごとの「実行結果」フォルダ(UNC)または大容量ストレージの URL。宛先の値は運用で確定し、確定するまで `artifact_store = disabled`。アクセス権の設定は範囲外。**(1)〜(4)は 2026-11-22 に台帳へ反映済み(承認)** |
| S3 既定は拒否 | ✅ | 許可リスト(リポジトリ、ツール、環境変数、エグゼキュータの環境変数の名前、能力のキー)はすべて既定が空。`artifact_store` の既定は `disabled`。外向きは遮断が既定(R17)。dev 用の選択肢は `prod` で拒否 |
| S4 担保の方法 | ✅ | 環境変数(R5)、引数の配列・パスの検査(R7)、成果物のパターン(R11)、ログのマスク(R10)、Git に書かない(エージェントは Git のクライアントを持たない。取得は取得のみ)、低権限のアカウントと ACL・ファイアウォール(R4、R17。ランナー PC の設定は 009)、テレメトリなし(R17)。各項目のテストは quickstart の V6〜V11、V37、V38 |
| S5 多層防御と限界 | ✅ | 2 アカウント + ACL + ファイアウォール + Job Object + 許可リスト + マスクの多層(R4〜R11)。限界(OS の既定で読めるもの、ツール自体の悪意、TOCTOU、制限付きトークンは将来)を、脅威モデルの 4 節に明記。実行を許可するツールとリポジトリを信頼できるものに限る(許可リスト) |
| S6 脅威モデルの先行 | ✅ | `docs/security/threat-model.md` の 4 節に T-W1〜T-W14 を追記した(本 plan の作業)。実装との対応は、実装の完了時点で 6 節に追加する |

### 中核原則

| 原則 | 判定 | 本 feature での扱い |
|---|---|---|
| 1 モジュール分割と再利用性 | ✅ | `runner-agent` は `runner-protocol` と httpx だけに依存し、`job_core*`・`job_profile_*`・`job_runner_service` を import しない。プロファイル・組み立ては外に置く。契約: ランナープロトコル(JSON Schema、版 1.1)、ポート + 契約テスト。動的なプラグイン読み込みを作らない(コード内の対応表 + 設定)。import-linter の契約を追加 |
| 2 DDD(軽量版) | ✅ | ランナーのコンテキストの外(エージェント)は、ID と契約で結合し、コアの内部を参照しない。ジョブの状態の確定はコアの集約が行う(エージェントは報告するだけ) |
| 3 プラットフォーム非依存 | ✅ | GitHub の語をエージェントとコアに入れない。取得は `SourceFetcher`・`SourceCredentialIssuer` のポートで、実アダプタは 005 |
| 4 作らないもの | ✅ | 1 ジョブ = 1 回の外部ツール実行。パイプライン・自動トリガ・プラグイン配布・ランナー PC の自動プロビジョニングは作らない(ランナー PC の構築は、009 の既存の枠組みに項目を渡す)。成果物は参照を渡すだけで、汎用の成果物リポジトリを作らない(保存先は共有フォルダ・外部のストレージ) |
| 5 運用上の要件 | ✅ | 強制中断(001)をエージェントが実行する(R6)。優先度の概念を持ち込まない。待機列の順序に関与しない |
| 6 監査ログ | ✅ | エージェントの監査(ローカル。詳細)と、コアの監査(`RUNNER_JOB_REPORT`、`LOG_READ`、`ARTIFACT_READ`。件数・理由コードだけ)。拒否・マスクの発動・リース切れ・許可リスト外の拒否を記録(FR-021) |
| 7 実行環境 | ✅ | Windows のみ。仮想化・コンテナを使わない。OS の機能(Job Object など)を使う |
| 8 ネットワーク境界 | ✅ | ランナーからサーバーへの接続のみ。着信を受けない(問い合わせ、中断の指示は応答で受ける)(R3) |
| 9 認可 | ✅ | ログ・成果物の参照は権限 `job.read_output`(RBAC)。ランナーの操作は `runner.report`・`job.execute` に限る(002、003) |
| 10 実行対象の固定 | ✅ | ソースはコミット識別子(`revision`)で固定して取得し、許可されたリポジトリだけ実行する(R12) |
| 11 テスト | ✅ | 契約テスト(Fake と実アダプタ)、パス・マスク・ペイロードの網羅(Hypothesis)、偽のコアでの結合試験、GitHub なしで通る(R18) |
| 12 未確定事項 | ✅ | spec の `[NEEDS CLARIFICATION]` は 0 件。保存先の宛先(運用で確定)と `https_storage` の製品は、条件として管理する |
| 13 WebUI | ➖ | 006。本 feature は、WebUI が使うログ・成果物の参照の API(契約)を定める |
| 14 環境構築の支援 | ⚠️ | 開発環境(`ops/dev`)に、4 パッケージ・004 の検証(V1〜V26)を加える(R20)。ランナー PC の構築(2 アカウント、ACL(作業フォルダ・状態フォルダ)、ファイアウォール、WinSW、設定の雛形、撤去。共有フォルダのアクセス権は範囲外)は、009 の `setup-runner.ps1` の項目として引き継ぎ、本 feature が項目と検査(V36〜V38)を定める。⚠️ 009 の基盤が未了のあいだは、完了の定義(ランナー PC での再現)を満たせない |

**ゲートの結果(Phase 0 前)**: 違反なし。原則 14(009 の基盤)は、条件を持ち越す(S2 の台帳の改定は反映済み)。→ Phase 0 へ進む。

**再評価(Phase 1 後)**: 設計成果物([data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md))を確認し、判定は上表のとおり。新たな外向きの宛先・用途固有の語は加えていない。001〜003 への変更(下記)は、既存の公開契約と受け入れテストを壊さない。
残る条件: (1) S2 の台帳の改定は 2026-11-22 に反映済み(解消)、(2) 成果物の保存先の宛先の運用の確定(アクセス権の設定は範囲外)、(3) 原則 14 の 009 の基盤、(4) 2 アカウント方式のスパイク(R4)。

## Project Structure

### Documentation (this feature)

```text
specs/004-runner-agent/
├── spec.md
├── plan.md                                    # 本書
├── research.md                                # Phase 0
├── data-model.md                              # Phase 1
├── quickstart.md                              # Phase 1(検証の手順)
├── contracts/
│   ├── runner-protocol.md                     # エンドポイント(追加)、振る舞いの約束、台帳との対応
│   ├── runner-protocol.schema.json            # メッセージ(JSON Schema、版 1.1)
│   ├── agent-config.schema.json               # エージェントの設定(JSON Schema、版 1)
│   └── ports.md                               # ポートの約束と契約テストの一覧
├── checklists/requirements.md
└── tasks.md                                   # Phase 2(/speckit-tasks で作成)
```

### Source Code (repository root)

```text
pyproject.toml                 # ワークスペースに runner-protocol、runner-agent、profile-equipment-check、runner-service を追加
.importlinter                  # 契約を追加(下記「依存規則」)

core/src/job_core/             # 001・002(下記「001〜003 への変更」だけを行う)
core-api/ core-persistence/ core-server/   # 003(同上)

runner-protocol/
├── pyproject.toml             # 依存なし(標準ライブラリのみ)
├── schemas/
│   └── runner-protocol.schema.json   # contracts/ のスキーマの正本(版 1.1)
└── src/job_runner_protocol/
    ├── messages.py            # LogChunk、FinishReport、ArtifactReference、Counters、SourceCredential、HeartbeatResult 等(値オブジェクト)
    ├── vocabulary.py          # FailureReason、Stream、ArtifactKind
    └── validate.py            # スキーマによる検査(送信前・受信後)

runner-agent/
├── pyproject.toml             # 依存: job-runner-protocol、httpx。job_core* を import しない
├── src/job_runner_agent/
│   ├── settings.py            # AgentSettings(値オブジェクト)、検証(profile の検査、許可リスト)
│   ├── agent.py               # 主ループ(登録 → 問い合わせ → 実行 → 報告)、生存通知、停止の信号
│   ├── execution.py           # Execution の状態遷移(準備 → 実行 → 収集 → 報告 → 後始末)
│   ├── executor.py            # Executor ポート、ExecutionContext、ExecutionPlan、Verdict、ExecutorRejected
│   ├── core_client.py         # CoreClient(再試行、バックオフ、確定の拒否の判定)
│   ├── guard/
│   │   ├── workpath.py        # WorkPath、WorkFolder(作成・検査・削除)、パスの検査(R7)
│   │   ├── environment.py     # 環境ブロックの組み立て(R5)
│   │   ├── allowlist.py       # リポジトリ・ツール・環境変数の名前の許可リスト
│   │   └── masking.py         # マスク(完全一致 + パターン。複数行)(R10)
│   ├── launcher/
│   │   ├── port.py            # ProcessLauncher ポート
│   │   ├── logon.py           # LogonLauncher(ログオン付きの生成 + Job Object。ctypes)
│   │   ├── direct.py          # DirectLauncher(dev のみ)
│   │   └── winapi.py          # ctypes の宣言(Job Object、リパースポイント、資格情報)
│   ├── logs.py                # 出力の読み取り、チャンク化、量の制限、待避(spool)、送信
│   ├── source.py              # SourceFetcher ポート、LocalDirectorySourceFetcher(dev のみ)
│   ├── artifacts/
│   │   ├── port.py            # ArtifactStore ポート
│   │   ├── collect.py         # パターンによる収集(リパースポイントを辿らない、上限)
│   │   ├── shared_folder.py   # SharedFolderArtifactStore(UNC の参照)
│   │   └── https_storage.py   # HttpsStorageArtifactStore(保存先の確定後)
│   ├── signals.py             # signal\ の異常・回復のファイルの監視(FR-023)
│   ├── journal.py             # 状態フォルダ: active、未報告の結果、監査(JSONL)
│   └── secrets.py             # SecretSource ポート、資格情報の保管機能の実装、環境変数(dev のみ)
└── tests/
    ├── unit/                  # パスの検査(網羅)、環境ブロック、マスク、設定の検証、状態遷移
    ├── acceptance/            # US1〜US6(偽のコア・偽のエグゼキュータ・偽のツール)、機密の検査、途絶
    ├── contract/              # プロトコルのスキーマ、各ポートの契約
    ├── windows/               # -m windows(Job Object、環境、リパースポイント、ACL)、-m twoaccount
    └── architecture/          # 依存規則・語彙・禁止 API・エグゼキュータの禁止 import

profile-equipment-check/
├── pyproject.toml             # 依存: job-runner-agent(ポートのみ)
├── src/job_profile_equipment_check/
│   ├── executor.py            # Executor の実装(引数・作業ディレクトリの組み立て、結果の解釈)
│   └── payload.py             # payload の形の検証
└── tests/                     # ExecutorContract、単体(コアなし)

runner-service/
├── pyproject.toml             # 依存: job-runner-agent、job-profile-equipment-check
├── config/                    # agent.example.toml、agent.dev.toml
└── src/job_runner_service/
    ├── wiring.py              # エグゼキュータの対応表(名前 → 実装。コード内)、ポートの選択と組み立て
    ├── settings.py            # TOML の読み込みと検証(profile の検査。prod で dev 用の実装を拒否)
    └── __main__.py            # 起動(停止の信号の処理、起動時の自己検査: ACL・ファイアウォール)

testing/src/job_testing/
├── runner_fakes/              # FakeRunnerCore(ASGI)、FakeExecutor 群、偽のツール、FakeProcessLauncher、FakeArtifactStore、FakeSourceFetcher、FakeSecretSource、送信を記録する偽のサーバー
├── core_fakes/                # JobLogStore のメモリ実装、abort_requested・リース切れの失敗の確定
├── api_fakes/                 # FakeSourceCredentialIssuer
└── contracts/                 # 本 feature の契約テスト群(ports.md の一覧)

ops/dev/                       # setup-dev.ps1 を拡張: 4 パッケージの uv sync、-VerifyOnly に V1〜V26
docs/security/threat-model.md  # 4 節を追記済み(T-W1〜T-W14)
```

**Structure Decision**: inputs/12-plan の構成に従い、`runner-protocol/`・`runner-agent/`・`profile-equipment-check/` を加え、組み立て専用の `runner-service/` を新設する(依存の向きを import-linter で守り、エージェント本体を用途固有の語から守るため。R1、Complexity Tracking)。

### 依存規則(`.importlinter` に追加。CI で検査)

- `job_runner_protocol` は、他の first-party を import しない(標準ライブラリのみ)。
- `job_runner_agent` は、`job_runner_protocol` だけを import する。`job_core`・`job_core_api`・`job_core_persistence`・`job_core_server`・`job_profile_*`・`job_runner_service`・`job_testing` を import しない。
- `job_profile_equipment_check` は、`job_runner_agent.executor`(ポートの型)と `job_runner_protocol` だけを import する。`subprocess`・`socket`・`http`・`urllib`・`ctypes` を import しない(アーキテクチャテスト)。
- `job_core*` は、`job_runner_*`・`job_profile_*` を import しない。
- 語彙の検査: `runner-agent`・`runner-protocol` に、用途固有の語(機材、評価、チェックツール)と GitHub の語を含めない。

### 001〜003 への変更(本 feature のタスクに含める)

001〜003 の公開の振る舞いと受け入れテストを壊さない追加に限る([data-model.md §3](data-model.md))。

1. `access.permission`: `JOB_READ_OUTPUT`(`job.read_output`)を追加する(権限は 14 種)。網羅テストを 16384 通りに広げる。003 の `access.example.toml`・`access.dev.toml` に、`operator`・`admin` への割り当ての例を加える。
2. `job.domain.audit`: `AuditOperation` に `RUNNER_JOB_REPORT`、`LOG_READ`、`ARTIFACT_READ` を追加する。
3. `job.application`: `ReportFinished` の入力を拡張(`exit_code`、`failure_reason`、`artifacts`、`counters`。省略可で、既存の呼び出しと互換)。`JobLogStore` のポートと `AppendLog`・`ReadLog`・`ListArtifacts` を追加する。
4. `runner.application`: `HeartbeatResult` に `abort_requested` を加える。`SweepRunners` が、リース切れの実行中のジョブを `FAILED`(理由 `lease_expired`)に確定する(R14)。
5. `core-api`: ランナー向け 3(`logs`、`source-credential`、`result` の拡張)と利用者向け 2(`GET /v1/jobs/{id}/logs`、`GET /v1/jobs/{id}/artifacts`)のエンドポイント、`SourceCredentialIssuer` のポート、OpenAPI のスナップショットの更新、`problem` の `code` の追加(`log_quota_exceeded`、`log_seq_conflict`、`target_not_running`、`source_not_available`)。
6. `core-persistence`: ログ・成果物の参照の表、Alembic のマイグレーション、`JobLogStore` の SQLAlchemy 実装。ジョブの保持期間の削除(`PurgeExpired`)に、ログ・参照を含める。
7. `job_testing`: `core_fakes` の更新、`api_fakes.FakeSourceCredentialIssuer`、`contracts` の追加。`.importlinter` と語彙の検査の更新。

### 他の feature への引き継ぎ

- **005(github-integration)**: `SourceCredentialIssuer` の実アダプタ(短命・読み取り専用の取得資格。出力先を台帳に追加)、`SourceFetcher` の実アダプタ(取得のみ。`.git` を残さない)、`SourceFetcherContract`・`SourceCredentialIssuerContract` を通すこと。
- **006(webui)**: ログの表示(`GET /v1/jobs/{id}/logs` の `after_seq` による追従。通知は状態の変更を契機に)、成果物の参照の表示(UNC パスは、コピーして開く。`url` はリンク)。権限 `job.read_output` による表示の切り替え。
- **007(notification)**: ログ・成果物の参照を含めない(変更なし)。
- **008(fault-tolerance)**: ランナー PC と評価機材の冗長化、エージェントの再起動時の `agent_restarted` の扱いとの整合。
- **009(environment-setup)**: ランナー用の構築スクリプト(`setup-runner.ps1`)の項目 — 2 つのローカルアカウント、作業フォルダ・状態フォルダの作成と ACL、ツールのアカウントの外向きの遮断の規則、資格情報の保管、WinSW の登録、`agent.toml` の雛形と検証(ドライラン)、撤去。成果物の保存先は、アクセス権の設定を**範囲外**とする(ランナーごとの「実行結果」フォルダの指定は設定。権限は運用)。大容量ストレージを使う場合の資格の保管だけを項目に含める。検査 V36〜V38。

## Complexity Tracking

| 違反・複雑さ | 必要な理由 | より単純な代替を採らない理由 |
|---|---|---|
| 4 つ目の新パッケージ `runner-service`(組み立て専用) | `runner-agent` から `job_profile_*` への import を作らず、起動時の設定でエグゼキュータを選ぶため(憲章 原則 1) | 本体に組み立てを置くと、用途固有の import が本体に入る(FR-022、SC-008 の違反)。`core-server` と同じ構造 |
| 2 つのアカウント(`LogonLauncher`)と、スパイクを要する構成 | 1 つのアカウントでは、外部ツールがエージェントのトークン・設定・状態を読める(S1) | ファイルの ACL だけでは、同じ主体からの読み取りを防げない。縮退(1 アカウント)は採らない(R4) |
| ログと成果物の参照のコア側の保存(001〜003 の変更) | WebUI での逐次の参照(FR-004)と、成果物の参照の通知(FR-025)の要件 | 別の保存先にすると、権限・保持期間・監査が二重になる。成果物は参照だけにして、本体は保存しない |
| `Executor` が「計画を返すだけ」で、起動をエージェントが行う | S4(環境・パス・シェルの非経由)を用途ごとの実装に依存せず保証するため | エグゼキュータが直接起動する案は、機密保護を用途ごとに再実装することになる(R7) |
