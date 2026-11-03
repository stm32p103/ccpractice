# バックログ(エージェント開発 + 機能開発)

セッションをまたいで開発を進めるための、**唯一の進捗の置き場**。
`manager` スキルがセッション開始時に読み、終了時に更新する。

- 状態: `todo` / `doing` / `trial`(作成済み・試用待ち) / `done` / `hold`
- 優先度: 高(今やる) / 中(次) / 低(必要になったら)
- 1セッション内の細かい作業は、ツールのTODO(タスクリスト)で管理し、ここには結果だけ書く。

---

## 今後の進め方(ロードマップ)

### フェーズA:仕様開発の型を作る(Spec Kit にならう)
Spec Kit の流れ(specify → clarify → plan → tasks → analyze)で、題材の1機能の**仕様を固める**。
自作は `concept` / `spec-reviewer` / `manager` だけ。足りない点はこのフェーズで洗い出す。

### フェーズB:実装・テスト用のエージェントとスキルを作る
仕様(tasks.md まで)が承認(G4)されたら、**実装に入る前に**、
実装・テスト・検証を担うエージェントとスキルを作る(AG-07〜AG-12)。
作るものは、フェーズAで固まった仕様(plan.md / contracts / tasks.md)の形に合わせる。

### フェーズC:実装・テストを回す
`/speckit.implement` + 実装エージェントで実装し、検証エージェントと PR レビューで確認する。
完了後に `spec-sync` で domain/ とルート索引に反映する。2機能目からは A→C を繰り返し、
足りないスキルを都度足す。

---

## エージェント・スキル開発のバックログ

| ID | 内容 | 種類 | 状態 | 優先 | フェーズ | 完了条件 / メモ |
|---|---|---|---|---|---|---|
| AG-01 | `concept` スキル | スキル | trial | 高 | A | 題材1機能で concept.md を作り、使い勝手を確認 |
| AG-02 | `spec-reviewer` エージェント | エージェント | trial | 高 | A | G1 前のレビューで指摘が出せること |
| AG-03 | `manager` スキル(窓口のマネージャー機能) | スキル | trial | 高 | A | セッション開始時に状況把握→提案ができること |
| AG-04 | Spec Kit の導入(`specify init --here --ai claude`) | 環境 | todo | 高 | A | `/speckit.*` が使える。plan 実行時に CLAUDE.md/AGENTS.md の自作部分が上書きされないか確認 |
| AG-05 | constitution 作成(`/speckit.constitution`) | 仕様 | todo | 高 | A | DDD・OpenAPI・テスト先行・spec-anchored の原則を記載 |
| AG-06 | `domain-model` スキル(specs/domain/ の作成・更新) | スキル | todo | 中 | A | 題材の plan 時に必要性を判断。不要なら hold |
| AG-07 | `openapi-contract` スキル(生成・lint・ルート統合) | スキル | todo | 中 | B | G3 の前に OpenAPI を検証できる |
| AG-08 | `backend-impl` エージェント(Python+ORM、テスト先行) | エージェント | todo | 中 | B | G4 承認後・実装前に作成。BE フレームワーク / ORM の選定が前提(題材の最初の `/speckit.plan` 時に選定) |
| AG-09 | `frontend-impl` エージェント | エージェント | todo | 中 | B | TypeScript + React + Fluent UI |
| AG-10 | `contract-tester` エージェント(実APIとOpenAPIの突き合わせ) | エージェント | todo | 中 | B | |
| AG-11 | `impl-reviewer` エージェント(仕様IDとの突き合わせ、別コンテキスト) | エージェント | todo | 中 | B | |
| AG-12 | `spec-sync` スキル(domain/・ルート索引への反映) | スキル | todo | 低 | C | 1機能目の完了時に作成 |
| AG-13 | GitHub Copilot での動作確認(`.github/agents/`、skills) | 移植 | todo | 低 | A〜C | 同じ構成で使えるか確認 |
| AG-14 | Spec Kit の extensions フックで自作スキルを起動できるか検証 | 検証 | todo | 低 | A | 結果で自動起動するかを決める |

## 機能の進捗(ゲート記録)

| 機能 | concept | G1 要件 | G2 設計 | G3 API | G4 タスク | 実装 | PR |
|---|---|---|---|---|---|---|---|
| (題材)備品マスタの登録・一覧・編集 | - | - | - | - | - | - | - |

記入例: `済 2026-11-10`、`差戻し(理由)`。

## 引き継ぎメモ(新しいものを上に)

- 2026-11-03: ワークフロー初期構成を作成(AGENTS.md / concept / spec-reviewer / manager / バックログ)。
  次は AG-04(Spec Kit 導入)→ AG-01(題材の concept 作成)。
