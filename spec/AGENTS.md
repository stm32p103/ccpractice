# AGENTS.md(Claude Code / GitHub Copilot 共通)

## 記述
- 短い単語・文で書く
- 箇条書きで書く

## 用語
- エージェント間で使う用語は `rules/agent-glossary.md` の用語を使う
- 未登録の用語は登録してから使う

## ルール
- エージェント・スキル用のルール: `rules/` 以下に作る

## 概要
- 方式: 仕様駆動開発(SDD)
- 土台: GitHub Spec Kit(`/speckit.*`)
- 不足分: 自作スキル・エージェントで補う
- 決定の経緯: Git の履歴

## 役割: 窓口 兼 マネージャー
- 開発者と直接やり取り: メインのエージェントのみ
- `manager` スキルで現状把握・次の提案:
  - セッション開始時
  - 「次は?」「状況は?」と聞かれた時
- 全部自分でやらない。段階ごとのスキル/コマンド/サブエージェントへ委ねる
- 必要なエージェント/スキルが未作成: 実装せず、作成を先に提案(`docs/backlog.md`)
- 同一セッションで別トピックに移る時: セッション切り替えを提案
- セッション終了時: バックログの状態と引き継ぎメモを更新

## ワークフロー
- 形式: 段階: 使うもの → 成果物(ゲート)
- 0 アイディア出し: `concept` スキル → `specs/concept/*.md`(なし。要件化で凍結)
- 1 要件: `/speckit.specify` → `/speckit.clarify` → `spec-reviewer` → `specs/NNN-*/spec.md`(✅G1)
- 2 設計: `/speckit.plan` + `specs/domain/` 更新 → `plan.md`, `data-model.md`(✅G2)
- 3 API 契約: plan の `contracts/`(OpenAPI) → `contracts/openapi.yaml`(✅G3)
- 4 タスク: `/speckit.tasks` → `/speckit.analyze` → `tasks.md`(✅G4)
- 5 実装: `/speckit.implement` + 実装エージェント(未作成) → コード・テスト(自動: テスト/lint)
- 6 検証: 検証エージェント(未作成) → レビュー結果(✅PR)
- 7 仕様同期: `spec-sync`(未作成) → `specs/domain/`, ルート索引(PR に含める)

### ゲート(✅)
- 開発者の明示的な承認まで次に進まない
- 承認後: `docs/backlog.md` の「機能の進捗」に記録

## 仕様の構成
- `specs/domain/<集約>.md`
  - 単位: 集約
  - 内容: 用語・不変条件・モデル
  - 常に最新(living spec)
- `specs/NNN-<ユースケース>/`
  - 単位: ユースケース(Spec Kit の機能フォルダ)
  - 完了後: 履歴として残す
  - 更新系: 主に 1 集約を参照
  - 参照系(CQRS の Q): 複数集約を読むのみ。不変条件なし
- `specs/concept/`
  - 内容: アイディア
  - 要件化時: `status: frozen`
- 要件 ID: 例 `REQ-001-03`。設計・タスク・テストから参照

## 開発者とのやり取り
- 会話: 日本語
- PR: 要レビュー箇所へのリンクを付ける

## 技術前提
- バックエンド: Python、DDD
- 永続化: PostgreSQL + SQLAlchemy
- マイグレーション: Alembic
- API: FastAPI + Pydantic v2
- API 契約: OpenAPI(FastAPI の生成物を正とする。`/speckit.plan` の `contracts/` と突き合わせる)
- 認証・認可: `Depends` で RBAC
- フロントエンド: TypeScript + React
- UI フレームワーク: 開発ごとに統一。基本は Fluent UI

## センシティブなデータ
- 禁止: 外部に送らない
- 対象:
  - パスワード、ハッシュ、セッション ID、秘密鍵
  - 環境変数の値
  - 本番データ、個人情報
  - 社内のホスト名、IP アドレス、ファイルパス
- 外部: Web 検索、Web の取得、外部サービス
- ログ、エラーメッセージ: 対象を含むものとして扱う
- エラーメッセージの検索: 対象を除去・一般化してから行う。できなければ検索しない
- エージェントに読ませない: 本番環境の秘密情報、データ、ログ、バックアップ
  - 理由: 読んだ内容は Claude の API に送信される
- テスト、試行環境: ダミーのデータのみ使う
- 本番環境の障害の解析: 開発者が対象を除去してから渡す
