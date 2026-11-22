# core-api — コアを HTTP API として公開する層

001・002 のコア(`job_core`)を、HTTP API(`/v1`)として公開する。FastAPI(同期のエンドポイント)。
**永続化・認証基盤の実装には依存しない**(ポートだけを使う。依存規則は `.importlinter`)。

- 仕様・設計: [`specs/003-core-api/`](../specs/003-core-api/)(spec、plan、research、contracts、quickstart)
- 契約: [`openapi/openapi-v1.json`](openapi/openapi-v1.json)(実装から生成するスナップショット。更新: `uv run python -m job_core_api.tools.export_openapi`)
- 公開の方式: 認証つきの `GET /openapi.json`

## 構成

| 場所 | 役割 |
|---|---|
| `job_core_api.app` | `create_app(deps)`。ルーター・ミドルウェア・例外ハンドラー・OpenAPI の組み立て |
| `job_core_api.deps` | ポートと設定の束(`ApiDependencies`)、コアのユースケースの束(`CoreUseCases`) |
| `job_core_api.access` | 認証(トークン・セッション・サービス用の認証情報)、アクセス設定(対応表)、監査 |
| `job_core_api.events` | 変更の通知(プロセス内のブローカー、SSE、発行) |
| `job_core_api.http` | ルーター、モデル、エラーの写像、ミドルウェア |
| `job_core_api.scheduler` | 定期処理(ランナーの定期処理、保持期間の削除、セッションの削除) |

## ポートの差し替え

実装は組み立てる側(`core-server`、テストの `build_api`)が選び、`ApiDependencies.assemble(...)` に渡す。

| ポート | 役割 | 実装 |
|---|---|---|
| `IdentityProvider` | 本人性と所属グループの確認 | 偽の実装(`job_testing.api_fakes`)、外部の認証基盤のアダプタ(005) |
| `ServiceCredentialRepository`・`SessionRepository` | 認証情報・セッションの永続化 | メモリ(`job_testing`)、SQLAlchemy(`core-persistence`) |
| `AccessConfigSource` | アクセス設定(対応表)の読み込み | TOML(`access.config_file`) |
| `ChangeBroker` | 変更の通知の仲介 | プロセス内(`events.broker`) |
| `SecretSource` | 秘密情報の取得 | 環境変数(開発・試験専用。`core-server`) |

## 運用上の前提(残るリスク)

- **API サーバーのプロセスは 1 つ**(uvicorn のワーカー数 1)。通知のリングバッファと定期処理がプロセス内にあるため、複数のプロセスでは通知の取りこぼしと定期処理の重複が起きる。
- **所属グループの反映の遅れ**: セッションはログイン時の所属グループを保持する。認証基盤での変更は、次のログイン(絶対 12 時間・無操作 2 時間)まで反映されない。`DELETE /v1/access/sessions?subject_id=` で即時に失効できる。
- **接続元の許可リストの限界**: 接続のアドレスだけを見る(`X-Forwarded-For` は信用しない)。リバースプロキシを置く構成では、プロキシのアドレスを許可する運用になる。
- 外向きの通信をしない(憲章 S2)。FastAPI の組み込みのテレメトリも無効にしている(`app.py::TELEMETRY_DISABLED`)。

## 互換の方針(`/v1`)

- URL に版を含める。**追加(エンドポイント・任意の項目・応答の列挙値)は同じ版で行い、破壊的変更は新しい版で提供する**。クライアントは、未知の項目・列挙値を無視する。
- 旧版は、3 か月以上の互換期間を設ける。`ApiSettings.deprecation_sunset` を設定すると、`/v1/` の応答に `Deprecation: true` と `Sunset` を付ける。
- 破壊的変更の検出: 公開した版の OpenAPI を `openapi/released/` に置くと、`tests/contract/test_openapi_snapshot.py` が現在の実装との比較で検出する(パス・操作・応答の項目の削除、必須項目の追加、型・列挙の縮小、認可の強化)。

## 検証

```powershell
uv run pytest core-api/tests            # 単体・受け入れ・契約(生成クライアント、schemathesis、SSE の実サーバー)
uv run pytest core-api/tests/perf -m perf   # 性能の目安
uv run lint-imports                     # 依存規則
```
