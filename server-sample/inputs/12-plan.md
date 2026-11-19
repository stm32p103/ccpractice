# /speckit.plan 入力(spec 承認後)

feature ごとに実行する。共通部分は全 feature に貼り付け、feature 固有部分を追加する。

## 共通の入力

```
## 技術スタック
- Python 3.12+、FastAPI、SQLAlchemy 2.0、Alembic、PostgreSQL(Windows 版)
- WebUI: TypeScript + React + Fluent UI(`@fluentui/react-components`、v9)。Modern Web Guidance(Chrome 等のチームによるエージェント用スキル)に従う。
- 環境構築・運用スクリプト: Windows PowerShell 5.1 以降(Windows 標準)。テストは Pester、静的検査は PSScriptAnalyzer。
- パッケージ管理: モノレポ。Python 側は uv のワークスペース等、WebUI 側は npm(または pnpm)で、モジュールごとに独立したパッケージとして管理する。
- 依存規則の検査: import-linter(CI で必須)

## リポジトリ構成(モジュール = 独立パッケージ)
- core/               ジョブ・ランナーのドメインとアプリケーション層(依存なし)
- core-persistence/   SQLAlchemy による永続化アダプタ
- core-api/           FastAPI(コアの HTTP 公開、認証・認可、OpenAPI)
- runner-protocol/    ランナープロトコルのスキーマ(エージェントと API が共有)
- runner-agent/       ランナーエージェント(Windows サービス)
- integrations/github/ 認証アダプタ、提出ゲートウェイ、ソース取得、書き戻し
- webui/              画面(TypeScript + React + Fluent UI。コア API の生成クライアントを使う)
- ops/                環境構築・運用スクリプト(server/、worker/、db/、common/、verify/)と設定ファイルの雛形
- notifiers/          通知アダプタ(メール/Teams 等)
- profiles/equipment-check/  最初の用途: 依頼ファイルの解釈、エグゼキュータ
- testing/            Fake(偽の認証基盤・提出経路・コア API・エグゼキュータ)と契約テスト

## 設計方針(DDD 軽量版 + ポート&アダプタ)
- 層: domain(集約・値オブジェクト・イベント) → application(ユースケース、ポート定義) ← adapters / interface
- 依存の向き: 連携・UI・用途固有 → core-api → core。core は標準ライブラリのみ。
- コンテキスト: job、runner、access、notification。コンテキスト間は ID 参照とドメインイベント。
- ジョブの状態遷移は集約メソッドに閉じ込める。不正な遷移は例外。
- 通知はトランザクショナル・アウトボックスで取りこぼしを防ぐ。
- キューの取得は SELECT ... FOR UPDATE SKIP LOCKED。ジョブの割り当てはリースで管理する。
- 公開契約: コア API は OpenAPI(クライアントを生成)、ランナープロトコルとイベントは JSON Schema。契約テストで検査する。
- 語彙検査: core / core-api / runner-agent に GitHub・用途固有の語を含めないことを、テストで検査する。
- 拡張は起動時の設定でポートの実装を指定する方式。動的なプラグイン読み込み機構は作らない。

## 機密保護の実装方針(憲章 S1〜S6、13-security-egress に従う)
- 書き出し台帳(E1〜E12)の各項目に、対応する実装箇所とテストを対応づける。台帳にない送信がないことを、送信を記録する偽のサーバーで検証する。
- runner-agent: ジョブごとの作業フォルダを新規作成して終了後に削除。外部ツールの環境変数は空から許可リストで構築(Windows では CreateProcess に環境ブロックを明示指定)。
  引数配列で起動(shell=False)。パスは正規化し、作業フォルダ外(.. 、絶対パス、シンボリックリンク、ジャンクション、予約デバイス名)を拒否。
- Windows の制限: 専用の低権限アカウント、作業フォルダ以外への ACL、Job Object(プロセスツリーの停止とリソース制限)、
  Windows ファイアウォール(外向き通信を許可先に限定)。AppContainer や制限付きトークンの採用可否は、脅威モデルを書いたうえで検討する。
- ワークフロー雛形: `permissions: contents: read, id-token: write` のみ。Secrets 不使用。環境変数・ファイル一覧を出力しない。git の書き込み操作を含めない。
  雛形に対して、禁止の操作(git push、actions/upload-artifact、env の出力)が含まれないことを検査するテストを置く。
- ログのマスク: 既知の機密パターンを、送信前に置換する(補助的な対策)。
- 通知・GitHub への書き戻し: スキーマで項目を固定し、ログ本文を型として含められない形にする。
- 検査の自動化: CI に、(1) 台帳と実装の整合を確認するテスト、(2) 禁止 API の使用検査(core / runner-agent での HTTP クライアントの直接利用など)を置く。
- 残るリスク(仮想化不可による隔離の限界)と、許可リストによる信頼の前提を、運用文書に明記する。

## WebUI の実装方針(TypeScript + React、Modern Web Guidance)
- 実装前に、スキルをインストールして有効にする(`npx modern-web-guidance@latest install` が推奨の手順。要確認)。
  実装時は、スキルの検索と取得(search / retrieve)でガイドを参照し、参照したガイドの ID を PR に記録する。
- ビルド: Vite 等で静的資産を生成し、フォント・スクリプトを同梱する(外部 CDN 不使用)。サーバーはビルド成果物を配信する。
- API クライアント: コア API の OpenAPI から、型付きクライアントを生成する(openapi-typescript 等)。手書きの型を作らない。
- リアルタイム更新: SSE(EventSource)。
- UI 部品: Fluent UI React v9(FluentProvider でテーマを適用、ライト/ダーク)。Fluent にない部品のみ独自に作る。
  ※ Fluent の既定のフォントは OS のシステムフォント(Segoe UI)を使う。外部のフォント配信は使わない。
  ※ Modern Web Guidance の推奨と Fluent の実装が食い違う場合は、アクセシビリティと安全性を優先し、判断を PR に記録する。
- TypeScript: strict。React は関数コンポーネントとフックを使う。ログや payload の表示は、HTML として解釈せず、テキストとして表示する。
- アクセシビリティと性能: キーボード操作、スクリーンリーダー、コントラストを満たす。基準は Modern Web Guidance に従う。
- テスト: コンポーネントは Vitest + Testing Library、画面の通し試験は Playwright(偽のコア API に接続)。
- 外部への通信: コア API のみ。テレメトリ・解析・外部資産なし(台帳 E11)。

## テスト
- core: ドメインの単体テスト(状態遷移・優先度・要件マッチング・権限)
- ポートごとの契約テストを、実アダプタと Fake で共有する。
- GitHub なしの結合テスト(Fake の認証基盤・提出経路 + core-api + runner-agent + Fake エグゼキュータ)を CI で常時実行する。
```

## feature 固有の追加

### 001 / 002(core)

```
- core パッケージのみを対象とする。HTTP・DB は扱わず、永続化はリポジトリのポートとして定義する。
- 要件マッチングは、能力(キー/値)と条件(一致・包含・版比較)を扱う純粋な関数として実装し、網羅的にテストする。
```

### 003(core-api)

```
- FastAPI + 認証/認可の依存関係(権限単位: require_permission)。
- 主体: 人間(認証基盤ポート経由のセッション)、サービス(失効可能なトークン)、ランナー(ランナーごとのトークン、ハッシュで保存)。
- イベント配信は SSE。
```

### 004(runner-agent)

```
- Python の常駐プロセスを Windows サービス化(WinSW または NSSM)。サーバーへの long polling。
- エグゼキュータ: job_type → 実装クラスの対応を設定ファイルで指定する。
- プロセス管理: Windows のジョブオブジェクトで、子プロセスごと停止する。
```

### 005(github-integration)

```
- GitHub App(Contents 読み取り、Checks 書き込み、組織メンバー確認)と GitHub OAuth(ログイン)。
- 提出: ワークフロー(workflow_dispatch)が、イントラのランナー上で、OIDC トークンを付けて提出ゲートウェイを呼ぶ。トークンは JWKS で検証する。
- 所属グループ→ロールの対応表は設定ファイル。
```

### 006(webui)

```
- 上の「WebUI の実装方針」に従う(TypeScript + React、Modern Web Guidance、コア API の生成クライアントのみを使う)。
```

### 007(notification)

```
- アウトボックスから送信する背景処理。再送の上限と間隔は設定。
```

### 008(fault-tolerance)

```
- 2 台の Windows PC に PostgreSQL ストリーミングレプリケーション(プライマリ/スタンバイ)を構成。
- アプリサーバーはステートレスにして両機に配置。通常は片系のみ稼働(Active/Standby)。
- ランナー・提出経路・WebUI は固定のホスト名(DNS の別名)でアクセスし、切替は別名の付け替え、または切替スクリプトで行う。
- 自動フェイルオーバーは行わず、スクリプト化した手動昇格を基本とする(誤判定による二重化を避けるため)。
- 定期バックアップと復元訓練。Windows サービスの自動再起動、ヘルスチェック。
- 2 台構成のセットアップは、009 の枠組み(ops/common)を使い、レプリケーション設定と昇格のスクリプトを追加する。
```

### 009(environment-setup)

```
- ops/ に PowerShell スクリプトを置く: server/setup-server.ps1、worker/setup-worker.ps1、db/migrate.ps1、verify/smoke-test.ps1、uninstall、common/(ログ、事前確認、設定の検証、ハッシュ検証、ACL/ファイアウォール/サービス登録の共通関数)。
- 設計: パラメータは設定ファイル(雛形を同梱)で与える。冪等(現在の状態を確認して差分のみ適用)。-WhatIf によるドライラン。実行前に事前確認。
- PostgreSQL: サイレントインストール、専用 DB/ロール(最小権限)、listen と pg_hba でイントラネットに限定。
- サービス: WinSW でコア API・ランナーエージェントを登録(自動起動、異常時の再起動)。ランナーは専用の低権限アカウントで実行。
- マイグレーション: db/migrate.ps1 が、版の確認 → pg_dump でバックアップ → Alembic upgrade → 検証。失敗時は復元手順を表示(Alembic の downgrade に依存しない)。
- 秘密情報: Windows の資格情報の保管機能(資格情報マネージャー)に保存する。ログ・コンソールに出さない(出力に渡す値を検査する関数を経由)。
  注意: 資格情報はアカウントごとに保管される。サービスの専用アカウントが読み出せるように、そのアカウントの文脈で保存する必要がある
  (例: 一度だけ専用アカウントとして実行する手順)。また、サービスとして動くプロセスからの読み出しには制約がありうる。
  採用前に、小さな検証(スパイク)で、「専用アカウントのサービスが読み出せること」と「他のアカウントが読めないこと」を確認する。
  成立しない場合の代替は、DPAPI(アカウントまたはマシンの範囲)で暗号化した ACL 制限ファイル。
- ランナーの登録: 管理者が発行した 1 回限りの登録コードで認証情報を払い出す。
- 取得物の検証: 公式サイトのドメインを許可リストに固定し、HTTPS で取得。版を固定し、公式のハッシュ(SHA-256)または署名(Authenticode)で検証して、不一致なら停止。構築後は外向き通信を遮断。
- テスト: Pester(冪等性、ドライラン、ログに秘密がないこと、専用アカウントの ACL)。PSScriptAnalyzer を CI で実行。
- 段階的な提供: 最初の試行(001 + 003)の前に、基盤(server/setup、db/migrate、common/、スモークテストの枠組み)を完成。以後、feature ごとに、構築・設定・マイグレーションとスモークテストの項目を追加する(004: worker/setup、005: 連携の設定、006: WebUI 資産の配置、008: 2 台構成)。
- 各 feature の合格条件: 新しい Windows PC に、スクリプトだけでその feature を試行できる環境を構築し、スモークテストが通ること。既存の環境に対するアップグレード(再実行)も通ること。
```
