# core-server — コンポジションルート

ポート実装を選び、`core-api` を組み立てて起動する。設定(TOML)の検証と、`profile` による保護を担う。

## 起動

```powershell
uv run python -m job_core_server --config core-server/config/server.dev.toml
```

- 設定は `core-server/config/` の雛形を参照(`server.example.toml`、`access.example.toml`、開発用の `server.dev.toml`、`access.dev.toml`)。**秘密情報を設定ファイルに書かない**(接続の秘密は `SecretSource` から名前で取得する)。
- uvicorn の**ワーカーは 1 つ**(通知の仲介と定期処理がプロセス内にあるため)。起動はサービスの管理(009 の WinSW など)に任せる。
- uvicorn のアクセスログは使わない(クエリ文字列を含むため)。アクセスログは API が、認証情報・クエリ・本文を出さずに記録する。

## `profile`(T-A9)

| profile | メモリ上のリポジトリ | 偽の認証基盤(Fake) | 環境変数の `SecretSource` |
|---|---|---|---|
| `dev` | 使える | 使える | 使える |
| `trial`・`prod` | **選ぶと起動を拒否** | **選ぶと起動を拒否** | 警告(開発・試験専用) |

試験用の実装(`job_testing`)は `dev` のときだけ import する(`pip install job-core-server[dev]`)。本番の構成には含めない。

## 現在の範囲

- 実装済み: 設定の読み込みと検証、`profile` の保護、`dev` の構成(偽の認証基盤、実時計、乱数の識別子。永続化は `memory` または `postgres`)、環境変数の `SecretSource`。`postgres` は、接続の秘密(`persistence.dsn_secret`)を取得し、起動時に最新のスキーマへ適用する(dev のみ。本番は 009 の `migrate.ps1`)。
- **未接続**: 外部の認証基盤のアダプタ(005)。`prod` の設定は、これが接続されるまで起動を拒否する(Fake・メモリへ黙って切り替えない)。

## 検証

```powershell
uv run pytest core-server/tests
```
