# 知識の書式（knowledge/ と public/）

ドメインのプラグインに、スキル・エージェントと一緒に知識をためるときの書式です。

- **スキルは「やり方」、知識は「事実と経緯」**（何がなぜそうなっているか）
- 人向けとAI向けで正本を分けない。1つのファイルに、人が読む本文と管理用の frontmatter を書く
- 他のドメインからは `public/index.md` だけを参照する（中身の knowledge/ は直接読まない）

## 置き場所

```
<ドメインのプラグイン>/
├ skills/
├ agents/
├ knowledge/          … 知識の正本（1ファイル1テーマ）
│  ├ device-y-quirks.md
│  └ ...
├ public/
│  └ index.md         … 公開用の索引（扱う範囲・扱わない範囲は人が書き、知識一覧は自動生成）
└ eval/
```

ひな形は `templates/domain/` にあります。

## knowledge/ の1ファイル

```markdown
---
id: device-y-quirks
title: 装置Yの癖
summary: 装置Yで通信Xの試験をするときに、手順書に書かれていない注意点
applies_to: [製品A v2.x, 製品B 全版]
sources:
  - 資料P.xlsx#シートS!行10
  - 記録Q.pdf p.4
owner: 担当者
review: draft
updated: 2026-11-12
---

（本文：人が読む説明。経緯、判断の理由、注意点）
```

| 項目 | 必須 | 内容 |
|---|---|---|
| `id` | ○ | ファイル名（拡張子なし）と同じ。英小文字、数字、ハイフン |
| `title` | ○ | 一言で何の知識か |
| `summary` | ○ | 索引に載せる1行の要約 |
| `applies_to` | ○ | どの製品・版に当てはまるか。当てはまる範囲が無い知識なら `[共通]` |
| `sources` | ○ | 原典（ファイルと、その中の場所）。要約で条件が落ちたときに戻れるようにする |
| `owner` | ○ | レビューする人・役割 |
| `review` | ○ | `draft`（未レビュー）または `reviewed`（レビュー済み） |
| `updated` | ○ | 最後に中身を変えた日 |

- 作業の中で人が補足・訂正した内容は、knowledge/ への変更（PR）として残す
- レビューが済んだら `review: reviewed` にする

## public/index.md

```markdown
# ドメインA

## 扱う範囲
（人が書く：このドメインで扱うこと）

## 扱わない範囲
（人が書く：よく間違えられるが、別のドメインで扱うこと）

## 知識一覧
<!-- BEGIN knowledge-list: build_public_index.py が生成する。手で編集しない -->
<!-- END knowledge-list -->
```

- 「扱う範囲」「扱わない範囲」は人が書く。他の人が「ここで聞いてよいか」を判断するいちばんの材料になる
- 知識一覧は `scripts/build_public_index.py` で knowledge/ の frontmatter から作る（LLMを使わないので、トークンを使わず、正本と食い違わない）
- ドラフトの知識も載せる。状態の欄に **ドラフト** と出し、件数も見出しに出す

```bash
python3 ai-process/scripts/build_public_index.py <ドメインのプラグイン>          # 生成して書き込む
python3 ai-process/scripts/build_public_index.py <ドメインのプラグイン> --check  # 古ければ終了コード1（CI用）
```

## 例や説明文の書き方

ai-process の例や説明文では、扱っている製品や具体的な技術が分かる書き方をしない。製品は A・B・C、通信・装置・形式は X・Y・Z のような記号で書く（例：「通信X」「装置Y」「製品A」）。
