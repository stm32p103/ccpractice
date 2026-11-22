# Implementation Plan: コア API — コアを HTTP API として公開する

**Branch**: `job_service`(spec ディレクトリ: `specs/003-core-api`) | **Date**: 2026-11-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-core-api/spec.md`

## Summary

001(ジョブ)・002(ランナー)のコアを、HTTP API(`/v1`)として公開する。FastAPI で、コアのユースケースに HTTP の形を与え、
**3 種類の主体(人間・サービス・ランナー)の認証**、**権限による認可の設定(所属グループ → ロール → 権限)**、**機械可読なエラー**、**SSE による変更の配信**、**認証基盤のポート**を加える。
ドメインの規則は持たない(認可の判定と拒否の監査は、001・002 のユースケースが行う)。あわせて、API を動かすための永続化(`core-persistence`)と起動の入口(`core-server`)を作る。

技術的な要点([research.md](research.md)):

- パッケージは `core-api`・`core-persistence`・`core-server` の 3 つ。`core-api` は `core` だけに依存し、永続化と認証基盤の実装は、`core-server` が起動時の設定で組み立てる(R1)。
- OpenAPI は実装から生成し、スナップショットと比べる。URL に版を含める(`/v1`)。互換期間は最低 3 か月(R2、R3)。
- 認証情報は不透明なトークン(`ss_`/`st_`/`rt_`)で、ハッシュだけを保存し、呼び出しごとに照合する。失効は即時(R4)。
- 人間の利用者は、`IdentityProvider` ポート → セッション(Cookie または Bearer)。権限は、所属グループを**現在の対応表**に通して、呼び出しごとに導く(R5、R6)。
- エラーは RFC 9457 の `problem+json`。コアの `code` を写し、開示する項目を型で固定する(R7)。
- 一覧は、履歴の検索(キーセットの頁送り)と、待機列(全件・順序つき)に分ける(R8)。
- イベントは SSE。直近 1000 件の再送と `resync`、15 秒ごとの認証の再確認。内容に自由な文字列を含めない(R9)。
- 外部への送信はしない。接続元の許可リストで、イントラネット外からの到達を拒否する(R11、R12)。
- 001・002 への小さな追加: 権限 `access.manage`、`PrincipalKind.ANONYMOUS`、監査の操作 6 種、`SearchJobs`(下記)。

## Technical Context

**Language/Version**: Python 3.12 以上(001 R1)

**Primary Dependencies**:
- 実行時: FastAPI、Pydantic v2、uvicorn(`core-api`・`core-server`)。SQLAlchemy 2.0、psycopg 3、Alembic(`core-persistence`)。TOML の読み込みは標準ライブラリ(`tomllib`)
- 開発時: 001・002 と同じ(pytest、Hypothesis、pytest-cov、jsonschema、import-linter、ruff、mypy)に、httpx(試験用のクライアント)、openapi-python-client(生成クライアントの試験)、schemathesis(OpenAPI に対する自動の試験)を加える
- 版は `uv.lock` で固定する。取得は公式の索引(PyPI)だけ(台帳 E15)

**Storage**: PostgreSQL(Windows 版)。コアのポートの実装(`core-persistence`)。試験・開発は、ユーザー領域の一時インスタンス(R13)

**Testing**: pytest(単体・受け入れ・契約・アーキテクチャ・性能)、Hypothesis、schemathesis、生成クライアントによる受け入れ試験。契約テストは Fake と SQLAlchemy(PostgreSQL)の両方で実行(憲章 原則 11)

**Target Platform**: Windows 10/11・Windows Server 上の CPython(憲章 原則 7)。イントラネット内のみ(原則 8)

**Project Type**: web-service(ライブラリ 2 + 起動の入口 1。`core-api`、`core-persistence`、`core-server`)

**Performance Goals**: 通常の負荷(同時に操作する利用者 50 人まで)で、単件の操作・一覧が 2 秒以内(SC-010)。変更の通知が 3 秒以内に届く(SC-007)

**Constraints**: API サーバーのプロセスは 1 つ(SSE のブローカーがプロセス内。R9)。外部への送信をしない(FR-023、FR-024)。認証情報の値・ハッシュを保存・ログ・応答・監査に平文で残さない(FR-026)。GitHub・用途固有の語を含まない(憲章 原則 3)

**Scale/Scope**: 利用者数十人、ランナー数十台、待機中のジョブ数百件(001 の想定)。SSE の接続は 200 まで。エンドポイント約 40、ポート 5 + 001 の拡張 1

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

判定: ✅ 適合 / ➖ 本 feature の対象外(担当の feature を記す) / ⚠️ 条件付き(条件を記す)

### S. 機密情報の保護

| 項目 | 判定 | 本 feature での扱い |
|---|---|---|
| S1 持ち出し禁止 | ➖ | 対象はワーカーとワークフロー(004、005)。API は作業フォルダ・環境変数を扱わない。ランナーから受け取る能力・異常の説明は、002 の許可リストと文字種の制限を通す |
| S2 書き出し台帳 | ✅ / ⚠️ | API が外へ書き出すのは、E4(ランナーから受け取る)・E16(ランナーの要求への応答)・E11(外部への通信なし)の範囲だけ。新しい書き出しは**加えない**(R12)。⚠️ 開発環境の構築スクリプトが、PostgreSQL の配布元から取得する(台帳 E15 の取得先の追加)ため、**台帳の更新とレビューを経てから実装する**(R17) |
| S3 既定は拒否 | ✅ | 未認証は拒否、どの所属グループにも当たらない利用者は `default_roles`(既定は閲覧のみ)、サービスの権限は上限の部分集合、ロールに実行用の権限を載せられない、接続元は許可リスト(R4、R6、R11) |
| S4 担保の方法 | ✅ / ➖ | API に関わる項目: テレメトリ・外部資産なし(禁止 API の検査と偽のサーバーでの検証。R12)、エラー・イベントに自由な文字列を含めない(R7、R9)、アクセスログに認証情報を出さない(R10)。ジョブの入力の検査・環境変数・パスの検査は 004 |
| S5 多層防御と限界 | ⚠️ | 接続元の許可リストは接続のアドレスだけを見る(プロキシ構成で弱まる)。所属グループの変更が次のログインまで反映されない。いずれも脅威モデルに残るリスクとして明記する(R18) |
| S6 脅威モデルの先行 | ⚠️ | `docs/security/threat-model.md` に 003 の節がない。**実装(/speckit-implement)の着手前に、「3B 003 コア API」の節(R18 の T-A1〜T-A12)を追記すること**を、tasks の最初のタスクとして置く |

### 中核原則

| 原則 | 判定 | 本 feature での扱い |
|---|---|---|
| 1 モジュール分割と再利用性 | ✅ | `core-api` は `core` だけに依存。永続化・認証基盤の実装は、起動時の設定で `core-server` が組み立てる(動的な読み込みを作らない)。公開契約: OpenAPI、`problem`・`change-event`・`access-config` のスキーマ、ポート。import-linter の契約を追加(R1)。互換性を壊す変更は版を上げる(R3) |
| 2 DDD(軽量版) | ✅ | ドメインの規則は持たず、コアのユースケースを呼ぶだけ。コンテキスト間の結合は ID とユースケースの入出力。サービス用の認証情報・セッションは、アクセスの文脈として `core-api` に置く(コアの内部を直接参照しない) |
| 3 プラットフォーム非依存 | ✅ | GitHub などの語を API・OpenAPI の文書・コードに含めない(語彙検査)。認証基盤は `IdentityProvider` ポートで、ログインの流れも provider に依存しない形(R5) |
| 4 作らないもの | ✅ | 認証基盤の独自実装(ユーザー管理・パスワード)を作らない。セッションとサービスの認証情報は、API の利用の入口であって認証基盤ではない。プラグインの動的な読み込み、パイプライン、自動トリガを作らない |
| 5 運用上の要件 | ✅ | API は、001 の操作(位置を指定した追加、スケジュール変更、取り消し、強制中断、やり直し)を権限の単位でそのまま公開する。優先度・割り込みの概念を API に持たない(FR-004)。待機列は全員が閲覧できる(R8) |
| 6 監査ログ | ✅ | 状態を変える呼び出しは、コアのユースケースが記録(代理元を含む)。API の層の操作(ログイン、サービス用の認証情報、対応表の変更、認証の失敗)は、コアの監査ログに操作の種類を 6 つ加えて記録する(R10) |
| 7 実行環境 | ✅ | Windows 上の CPython。PostgreSQL は公式の Windows 版。仮想化・コンテナを使わない(R13) |
| 8 ネットワーク境界 | ✅ | bind するアドレス + 接続元の許可リスト + ファイアウォール(009)。ランナーへの着信接続なし(R11、R16) |
| 9 認可 | ✅ | 権限単位の RBAC。所属グループ → ロール → 権限は設定で変更できる(R6)。可否は権限だけで判定し、主体の種類を使わない。`access.manage` を 1 つ加える |
| 10 実行対象の固定 | ➖ | 005 / 004 |
| 11 テスト | ✅ | 認証・認可の網羅、契約テスト(OpenAPI、スキーマ、ポート。Fake と実アダプタの両方)、生成クライアントによる結合試験、偽の認証基盤で GitHub なしに通す(R15) |
| 12 未確定事項 | ✅ | spec の `[NEEDS CLARIFICATION]` は 0 件。既定値(セッションの期限、上限)は research に明記し、設定で変えられる |
| 13 WebUI | ➖ | 006。ただし、WebUI が使う OpenAPI・Cookie・SSE の契約は本 feature が定める |
| 14 環境構築の支援 | ⚠️ | 開発環境(`ops/dev`)に、3 パッケージ・一時の PostgreSQL・V19〜V28 を加える。サーバーでの試行は、009 の基盤(`setup-server.ps1`、`migrate.ps1`)が先にできていることが前提で、本 feature はそこに API のサービス登録・設定の雛形・マイグレーション・スモークテストの項目を加える(R17)。⚠️ 009 の基盤が未了のあいだは、完了の定義(サーバーでの再現)を満たせない |

**ゲートの結果(Phase 0 前)**: 違反なし。S2・S5・S6・原則 14 は、条件(台帳のレビュー、脅威モデルの追記、009 の基盤)を持ち越す。→ Phase 0 へ進む。

**再評価(Phase 1 後)**: 設計成果物([data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md))を確認し、判定は上表のとおり。
新たな外向きの通信・用途固有の語は加えていない。001・002 への変更(下記)は、両者の公開契約と受け入れテストを壊さない。残る条件は S2(台帳のレビュー)、S5・S6(脅威モデルの追記)、原則 14(009 の基盤)。

## Project Structure

### Documentation (this feature)

```text
specs/003-core-api/
├── spec.md
├── plan.md                                    # 本書
├── research.md                                # Phase 0
├── data-model.md                              # Phase 1
├── quickstart.md                              # Phase 1(試行・検証の手順)
├── contracts/
│   ├── http-api.md                            # エンドポイント、権限、エラーの対応(設計時の契約)
│   ├── ports.md                               # ポートの約束と契約テストの一覧
│   ├── problem.schema.json                    # エラーの応答(JSON Schema、版 1)
│   ├── change-event.schema.json               # 変更の通知(JSON Schema、版 1)
│   └── access-config.schema.json              # アクセスの設定(JSON Schema、版 1)
├── checklists/requirements.md
└── tasks.md                                   # Phase 2(/speckit-tasks で作成)
```

### Source Code (repository root)

```text
pyproject.toml                 # ワークスペースに core-api、core-persistence、core-server を追加
.importlinter                  # 契約を追加: api-independent-of-impl、persistence-independent-of-server、core-independent-of-api(R1)

core/src/job_core/             # 001・002(下記「001・002 への変更」だけを行う)

core-api/
├── pyproject.toml             # 依存: job-core、fastapi、uvicorn。job_core_persistence を import しない
├── openapi/
│   └── openapi-v1.json        # 生成物のスナップショット(R2)
├── src/job_core_api/
│   ├── app.py                 # create_app(deps): ルーターの登録、ミドルウェア、例外の写像
│   ├── deps.py                # ApiDependencies: コアの依存、ポートの束、設定
│   ├── settings.py            # ApiSettings(値オブジェクト。読み込みは core-server)
│   ├── http/
│   │   ├── middleware.py      # 接続元の許可リスト、request_id、応答ヘッダ、本文の上限、アクセスログ
│   │   ├── authn.py           # 認証の依存関係: Bearer / Cookie → Principal(R4)
│   │   ├── errors.py          # 例外 → problem の写像の表(R7)
│   │   ├── schemas.py         # 要求・応答の Pydantic モデル(コアの値の写し)
│   │   └── routers/           # auth.py、jobs.py、queue.py、runners.py、allowlist.py、audit.py、access.py、runner_protocol.py、events.py、health.py
│   ├── access/
│   │   ├── ports.py           # IdentityProvider、ServiceCredentialRepository、SessionRepository、AccessConfigSource
│   │   ├── config.py          # AccessConfig、検証、permissions_of(groups)(R6)
│   │   ├── credentials.py     # サービス用の認証情報の発行・失効(ユースケース)
│   │   ├── sessions.py        # ログイン・ログアウト・有効の判定(ユースケース)
│   │   ├── authenticate.py    # 値の先頭による種類の判別と照合(R4)
│   │   └── audit.py           # API の層の監査の記録、認証失敗の窓による抑制(R10)
│   ├── events/
│   │   ├── ports.py           # ChangeBroker、PendingChange
│   │   ├── broker.py          # プロセス内のブローカー(リングバッファ、購読者の列)
│   │   ├── publisher.py       # 状態を変えるユースケースの成功後に通知を作る(R9)
│   │   └── sse.py             # text/event-stream の整形、keepalive、認証の再確認
│   └── scheduler.py           # SweepRunners・PurgeExpired・期限切れのセッションの削除(R20)
└── tests/
    ├── unit/                  # 対応表、認証の判別、写像の表、ブローカー、窓による抑制
    ├── acceptance/            # US1〜US9、生成クライアントの試験、イベント、書き出し(偽のサーバー)
    ├── contract/              # OpenAPI のスナップショット・破壊的変更、schemathesis、problem・change-event・access-config
    ├── architecture/          # 依存規則・語彙・禁止 API の検査
    └── perf/                  # 50 人の同時の利用者

core-persistence/
├── pyproject.toml             # 依存: job-core、job-core-api(ポートの定義)、sqlalchemy、psycopg、alembic
├── src/job_core_persistence/
│   ├── engine.py              # 接続(SecretSource から秘密を取得)
│   ├── models.py              # 表の定義(data-model.md §5)
│   ├── unit_of_work.py        # SqlUnitOfWork(001・002 の RunnerUnitOfWork を実装。version の楽観的排他)
│   ├── repositories/          # jobs、queue、audit、outbox、runners、leases、tokens、allowlist、service_credentials、sessions
│   └── migrations/            # Alembic(空の DB から最新まで)
└── tests/                     # 契約テスト(PostgreSQL)、マイグレーション

core-server/
├── pyproject.toml             # 依存: job-core、job-core-api、job-core-persistence
├── config/                    # server.example.toml、access.example.toml、server.dev.toml、access.dev.toml
├── src/job_core_server/
│   ├── settings.py            # TOML の読み込みと検証(profile = "dev" 以外では Fake・メモリを拒否。T-A9)
│   ├── wiring.py              # ポートの実装の選択と組み立て(起動時の設定による差し替え)
│   └── __main__.py            # uvicorn の起動(ワーカー数 1)
└── tests/                     # 設定の検証、profile、組み立て

testing/src/job_testing/
├── api_fakes/                 # FakeIdentityProvider、メモリ上の ServiceCredential・Session のリポジトリ、AccessConfigSource、API のテスト用の組み立て(build_api())
└── contracts/                 # 本 feature のポートの契約テスト群(ports.md の一覧)

ops/dev/                       # setup-dev.ps1 を拡張: 3 パッケージの uv sync、PostgreSQL の一時インスタンス(台帳のレビュー後)、-VerifyOnly に V19〜V28
docs/security/threat-model.md  # 「3B 003 コア API」を追記(最初のタスク)
```

**Structure Decision**: inputs/12-plan の構成に従い、`core-api/`・`core-persistence/` を加え、組み立て専用の `core-server/` を新設する(依存の向きを import-linter で守るため。R1、Complexity Tracking)。
ランナープロトコルの共有スキーマ(`runner-protocol/`)は 004 で作る。本 feature のランナー向けのエンドポイントは、002 のユースケースの形を HTTP に写すだけの最小版(R16)。

### 001・002 への変更(本 feature のタスクに含める)

001・002 の公開の振る舞いと受け入れテストを変えない、小さな追加に限る(data-model.md §6)。

1. `access.permission`: `ACCESS_MANAGE`(`access.manage`)を追加する。権限は 13 種になり、001・002 の権限の網羅テストは 8192 通りに広がる(既存の判定は変わらない)。
2. `access.principal`: `PrincipalKind.ANONYMOUS` を追加する。
3. `job.domain.audit`: `AuditOperation` に、`LOGIN`、`LOGOUT`、`AUTH_FAILED`、`SERVICE_CREDENTIAL_ISSUE`、`SERVICE_CREDENTIAL_REVOKE`、`ACCESS_CONFIG_CHANGE` を追加する。
4. `job.application`: `SearchJobs` の問い合わせ(`JobSearchCriteria`、`JobPage` への変換)と、`JobRepository.search` のポートを追加する(R8)。`ListJobs` は変えない。
5. `job_testing.core_fakes`: メモリ上の `JobRepository.search` を実装し、`build_core()` が追加の権限・問い合わせを使えるようにする。`job_testing.contracts` に `JobSearchContract` を追加し、既存の契約テストを SQLAlchemy 実装でも実行できるようにする(実装を差し替えるフィクスチャ)。
6. `.importlinter`: `job_core` が `job_core_api`・`job_core_persistence`・`job_core_server` を import しない契約を加える。`core/tests/architecture` の語彙の検査の対象に `core-api` を加える(禁止語の一覧は共通)。

### 他の feature への引き継ぎ

- **004(runner-agent)**: ランナー向けのエンドポイント(§2.6)を、ログ・成果物の送信、長時間の待ち受け(long polling)、再送の約束で拡張し、スキーマを `runner-protocol/` に切り出す。ランナーの異常の申告を PC 内のツールから受ける経路。
- **005(github-integration)**: `IdentityProvider` の実アダプタ(OAuth。出力先を台帳に追加する)、所属グループ → ロールの対応表の初期値(`access.toml`)、提出ゲートウェイ(サービスの認証情報で `on_behalf_of` つきの提出。位置指定の扱い)、`IdentityProviderContract` を通すこと。
- **006(webui)**: OpenAPI から生成するクライアント、Cookie のセッション、SSE の購読と `resync`、`GET /v1/auth/session` の `permissions` による表示の切り替え。
- **007(notification)**: コアのアウトボックス(ジョブ完了イベント)から送る。本 feature の SSE とは別の仕組み(R9)。
- **008(fault-tolerance)**: API サーバーのプロセスが 1 つであること(SSE のブローカーがプロセス内)を、Active/Standby の設計で守る。複数プロセスに増やす場合のブローカーの差し替え。
- **009(environment-setup)**: `server.toml`・`access.toml` の雛形の配置と ACL、API のサービス登録(WinSW)、`migrate.ps1` からの Alembic、DB の秘密の保管(資格情報の保管機能のスパイク)、受信のファイアウォール規則。

## Complexity Tracking

Constitution Check に、正当化を要する違反はない。次の 1 点は、憲章の規律との関係を記録しておく。

| 判断 | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| 12-plan の構成にない 3 つ目のパッケージ `core-server/` を加える | `core-api` が `core-persistence` や認証基盤のアダプタを import しないまま、起動時の設定で実装を組み立てる場所が要る(憲章 原則 1「ポート + 起動時の設定による差し替え」) | `core-api` の中で組み立てる — `core-api` が永続化の実装を import することになり、依存規則(import-linter)で守れない。文字列からの動的な import — 動的な読み込み機構を作らない規律に反する |
