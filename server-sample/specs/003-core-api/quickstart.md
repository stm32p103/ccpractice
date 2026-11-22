# クイックスタート(試行と検証の手順): コア API — コアを HTTP API として公開する

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

003 は、001・002 のコアを HTTP API として公開する。自動の検証は、偽の認証基盤(Fake)・メモリ上のリポジトリ・一時の PostgreSQL で動き、GitHub・ランナーの実機・外部のネットワークを使わない。
サーバーでの試行(Windows サービス、実 DB)は、009 の基盤が先にできていることが前提(research R17)。本書の §4 は、その前に開発 PC で行う手動の試行。

---

## 1. 前提と構築

001・002 の [quickstart.md](../001-core-job-queue/quickstart.md) §1〜§2 と同じ(`.\ops\dev\setup-dev.ps1`)。003 は、次を `ops/dev` に加える(research R17)。

- ワークスペースの 3 パッケージ(`core-api`、`core-persistence`、`core-server`)の `uv sync`。
- PostgreSQL(公式の Windows 用バイナリの zip)の取得(版とハッシュを固定。ハッシュの不一致なら停止。取得先は設定の許可リストに限る)と、ユーザー領域の一時インスタンスの作成・起動・撤去(`-WhatIf` でドライラン)。
  **取得先のドメインを台帳 E15 に追加するレビューが済むまで、この手順は有効にしない**(S2)。レビュー前は、PostgreSQL を使う V26 を「保留」として扱い、他の検証は実行できる。
- 秘密情報(DB の接続の秘密)は、開発では環境変数だけを使う(`SecretSource` の開発用の実装)。ログ・コンソールに出さない。

## 2. 検証の実行

001・002 の V1〜V18 に、次を加える。`.\ops\dev\setup-dev.ps1 -VerifyOnly` は V1〜V28 を順に実行する。

| # | 検証 | コマンド | 期待 |
|---|---|---|---|
| V19 | OpenAPI の契約: スナップショットとの一致、直前の公開版との破壊的変更の検査 | `uv run pytest core-api/tests/contract/test_openapi_snapshot.py` | 一致。意図しない変更・破壊的変更があれば失敗(SC-008) |
| V20 | 応答が定義に適合する(`schemathesis`) | `uv run pytest core-api/tests/contract/test_schemathesis.py` | 全エンドポイントで、定義にない応答・形式がない(FR-003) |
| V21 | 生成クライアントだけでの一連の操作 | `uv run pytest core-api/tests/acceptance/test_generated_client.py` | 提出 → 参照 → スケジュール変更 → 取り消し → 強制中断 → やり直し → ランナーの管理 → 監査ログの参照が成立(SC-001) |
| V22 | 認証・認可の網羅(3 種類の主体 × 13 権限の部分集合 × 操作) | `uv run pytest core-api/tests/unit/test_authn_authz.py` | 期待どおり。主体の種類で結果が変わらない(権限だけで決まる) |
| V23 | 受け入れシナリオ(US1〜US9)、代理提出、失効の即時性、ランナーの越権、偽の認証基盤、対応表の変更 | `uv run pytest core-api/tests/acceptance` | 全件成功。テスト名に `us2_1` などのシナリオ番号を含む(SC-002〜SC-006) |
| V24 | エラーの形式と開示(写像の表、`problem.schema.json` への適合、認証情報・payload・ログ・内部の文字列が現れない) | `uv run pytest core-api/tests/contract/test_problem.py` | 全件成功(SC-006、T-A1、T-A8) |
| V25 | イベントの配信(受信、再接続での補い、`resync`、切断、内容の検査) | `uv run pytest core-api/tests/acceptance/test_events.py` | 通常の負荷で 3 秒以内に受信(SC-007)。通知に自由な文字列がない |
| V26 | 永続化の契約テスト(001・002・003 のポートを、Fake と SQLAlchemy(PostgreSQL)の両方で) | `uv run pytest testing/tests core-persistence/tests -m postgres` | 同じ契約テストが両方で成功。マイグレーションが空の DB から最新に適用できる |
| V27 | 依存規則・語彙・禁止 API・書き出し(偽のサーバーで外向きの通信 0 件) | `uv run lint-imports` と `uv run pytest core-api/tests/architecture core-api/tests/acceptance/test_egress.py` | 違反 0。外向きの通信 0 件(SC-009) |
| V28 | 性能の目安 | `uv run pytest core-api/tests/perf -m perf` | 50 人の同時の利用者で、単件の操作・一覧が 2 秒以内(SC-010) |

V4(契約テスト)、V6(依存規則)、V7(語彙・禁止 API)、V10(静的検査)は、003 の追加分(`core-api`、`core-persistence`、`core-server`)も対象になる。
001・002 の受け入れテスト(V8、V14 など)は、変更なしで通ること(plan「001・002 への変更」の確認)。

## 3. 手で確かめるシナリオ(対話型・メモリ上)

`uv run python -m job_core_server --config core-server/config/server.dev.toml` で、開発用の設定(`profile = "dev"`。メモリ上のリポジトリ、`FakeIdentityProvider`、`127.0.0.1:8080`)のサーバーを起動する。
`profile = "dev"` 以外では、Fake の認証基盤・メモリ上のリポジトリを選べない(T-A9)。以下は PowerShell の `Invoke-RestMethod` の例(`$h` は `Authorization` ヘッダ)。キーは記号(`k1`)を使う(用途固有の語を使わない)。

1. **ログイン**(US4-1): `POST /v1/auth/login` に `{"proof": {"subject": "u1", "groups": "g-admin"}, "delivery": "token"}` → `session_token`(`ss_...`)を受け取る。`GET /v1/auth/session` で、対応表(`access.dev.toml`)から導いた権限が返る。
2. **ランナーの作成と登録**(US3、002 US1): 管理者で `PUT /v1/capability-allowlist`(`k1`: 単一値)→ `POST /v1/runners`(`name: r-a`)で `rt_...` を受け取る → そのトークンで `POST /v1/runner/registration`(`{"capabilities": {"k1": "v"}}`)。
3. **提出と取得**(US1): 一般の利用者で `POST /v1/jobs`(`job_type`(必須)、要件 `{"all": [{"key": "k1", "op": "eq", "value": "v"}]}`)→ `201`。ランナーのトークンで `POST /v1/runner/job-requests` → 割り当て(ジョブ定義とリースの期限)。`POST /v1/runner/jobs/{id}/result` で終了を報告 → `GET /v1/jobs/{id}` が `succeeded`。
4. **代理提出**(US2): `POST /v1/service-credentials`(`name: svc-a`、`permissions: [job.submit, job.submit_on_behalf]`)で `st_...` を受け取る → そのトークンで、`on_behalf_of: "u2"` を付けて `POST /v1/jobs` → `201`。一般の利用者が同じ指定をすると `403`。`GET /v1/audit-log` で、名義上の提出者(`u2`)と代理元(サービス)の両方を確認する。
5. **失効**(US2-4、US3-2): `DELETE /v1/service-credentials/{id}` → その `st_...` での呼び出しが `401`。`DELETE /v1/runners/{id}/token` → ランナーの `POST /v1/runner/job-requests` が `401`。
6. **スケジュール変更**(US1-2): 待機中のジョブを複数提出 → 権限を持つ利用者で `POST /v1/jobs/{id}/reschedule`(`placement`: 別のジョブの `before`)→ `GET /v1/queue` の順序が変わる。実行中のジョブは変わらない。
7. **購読**(US6): 別の窓で `curl.exe -N -H "Authorization: Bearer ss_..." http://127.0.0.1:8080/v1/events` → 手順 3・6 の操作で、`job.changed`・`queue.changed` が届く。切断して `Last-Event-ID` を付けて再接続すると、取りこぼした分が届く。
8. **対応表の変更**(US4-2): `access.dev.toml` で、あるグループのロールを変えて `POST /v1/access/reload` → 同じ利用者の次の呼び出しから、新しい権限(`GET /v1/auth/session` の `permissions` で確認)。不正な設定(未定義のロール)では `400 access_config_invalid` で、現在の対応表が保たれる。
9. **エラー**(US7): 要件を満たすランナーがない提出 → `422 no_eligible_runner`、権限のない操作 → `403 permission_denied`(`required_permissions` つき)、終了済みのジョブの取り消し → `409 invalid_state_transition`。いずれも `application/problem+json`。
10. **ネットワーク境界**(FR-022): `server.dev.toml` の `allowed_networks` から接続元(`127.0.0.1`)を外して再起動 → 同じ要求が `403 network_not_allowed`。

## 4. サーバーでの試行(009 の基盤の後)

009 の `setup-server.ps1` と `db/migrate.ps1` で、PostgreSQL・サービス(WinSW)・設定ファイル(`server.toml`、`access.toml`。雛形は `core-server/config/`)を構築し、`verify/smoke-test.ps1` で次を確認する(R17)。

1. マイグレーションが空の DB から最新に適用され、再実行しても変化がない(冪等)。
2. ログイン(認証基盤は、本 feature では Fake を使えない。試行用の認証基盤のアダプタが要る場合は、005 の完了後、または試行用の設定で `profile = "trial"` の固定ユーザーを使う — tasks で扱いを決める)。
3. 提出 → 参照 → ランナーの取得 → 終了の報告の一巡。
4. サービスの再起動後も、セッション・認証情報・ジョブが残る(永続化)。

## 5. 受け入れ基準との対応

| 受け入れ基準(spec) | 検証 |
|---|---|
| 生成したクライアントだけで、提出・参照・管理が行える | V21(SC-001) |
| サービス主体が代理で提出でき、監査ログに代理元が残る。一般の利用者はできない | V23(US2)、§3 手順 4 |
| 失効したランナーの認証情報では、ジョブを取得できない | V23(US3)、§3 手順 5 |
| 偽の認証基盤で、GitHub なしにログインして一連の操作を試験できる | V21〜V23(SC-002)、§3 手順 1 |
