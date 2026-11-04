# agent-skill-builder-coach（プロジェクト用）

このフォルダを VS Code でワークスペースとして開くと、スキル `agent-skill-builder-coach` が使えるようになります。

## 構成

```
.claude/skills/agent-skill-builder-coach/SKILL.md
```

`.claude/skills/` に置いておけば、次のどちらからも読み込まれます。
- **Claude Code**（VS Code 拡張、CLI）
- **GitHub Copilot**（VS Code のエージェントモード、Copilot CLI。`.github/skills/` と `.claude/skills/` の両方を探しに行きます）

Copilot だけで使う場合は、`.claude/skills/` を `.github/skills/` に移しても動きます。
**両方の場所に同じスキルを置くと、Copilot から二重に見えることがある**ので、置くのはどちらか一方にしてください。

## 既存のプロジェクトに入れる場合

`.claude/skills/agent-skill-builder-coach/` を、そのプロジェクトのルートにある `.claude/skills/`（または `.github/skills/`）の下にコピーします。

## 使い方

チャット（Copilot はエージェントモード）で、自動化したい業務を話します。全体でも一部だけでも構いません。

> 仕様書に従ってCのコードを書かせて、別のエージェントに仕様と合っているか照合させたい

スキルが読み込まれると、返答は「現在地 → 次にやること → 決めること（[D01]…）」の形になります。
自動で読み込まれないときは、「agent-skill-builder-coach を使って」と書き添えてください（Copilot なら `/agent-skill-builder-coach` でも呼べます）。

## 確認

- Copilot：回答の **References** 欄に SKILL.md が表示されれば、読み込まれています。
- Copilot：VS Code の設定でエージェントスキルが無効になっている場合は、`chat.useAgentSkills` を有効にしてください。
