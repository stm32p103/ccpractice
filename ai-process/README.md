# ai-process（エージェント・スキル体制）

自分用のエージェント・スキル体制を、版を付けて管理するパッケージです。体制の開発と評価をセットで持ち、更新するときに「何が良くなったか」を説明できるようにします。

## 中身
| 場所 | 中身 |
|---|---|
| `skills/agent-skill-builder-coach/` | スキルを作るスキル（構築の伴走、ゲートと人の確認の設計、評価、版管理） |
| `skills/drafting-openapi-contract/` | 要件 → OpenAPI 契約 |
| `skills/writing-contract-tests/` | 契約 → テストケース一覧 →（承認）→ テストコード |
| `agents/eval-judge.md` | 評価の採点役（読み取り専用） |
| `eval/` | 評価の仕組みの共通部（どの題材でも使う） |
| `eval-cases/<題材>/` | 題材固有部（入力、正解の判定方法、判定スクリプト、採点基準） |
| `scripts/export_copilot.py` | VS Code / GitHub Copilot 向けに `.github/` へ書き出す |
| `scripts/pack_skill.py` | Claude アプリにアップロードするスキルの zip を作る |
| `docs/` | 版の付け方、決定記録 |

## 正本と配り方
正本はこのリポジトリです。各環境へは一方向に配り、配った先では直接編集しません。

| 配り先 | 方法 |
|---|---|
| Claude Code | `/plugin marketplace add stm32p103/ccpractice` → `/plugin install ai-process@ccpractice` |
| VS Code / Copilot | `python3 ai-process/scripts/export_copilot.py --target <対象リポジトリ>` |
| Claude アプリ | `python3 ai-process/scripts/pack_skill.py <スキル名>` で作った zip をアップロード |

コマンド名や設定項目は版によって変わることがあるので、最新のドキュメントで確認してください。

## 評価
```bash
pip install fastapi httpx pytest pyyaml openapi-spec-validator
python3 ai-process/eval-cases/equipment-loan/selftest/run_selftest.py   # 判定の仕組み自体のテスト
```
実行の手順は [eval/README.md](eval/README.md)、題材の説明は [eval-cases/equipment-loan/README.md](eval-cases/equipment-loan/README.md) にあります。
