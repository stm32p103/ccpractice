---
name: comment-parser-catalog
description: dwarf_symbol_resolver の既存のコメントパーサ (コメント形式) を集約し、一覧 (CATALOG.md と formats/__init__.py の ALL_FORMATS) を再生成して、各形式の自己テストと形式どうしの衝突を確認する。「コメントパーサの一覧」「コメント形式のカタログを更新」「パーサが衝突していないか確認」と言われたとき、および comment-parser スキルの途中で呼ばれる。
---

# コメントパーサの集約 (カタログ)

`src/dwarf_symbol_resolver/comments/formats/` にある形式 (コメントパーサ) を集め、次を最新にする。

- `src/dwarf_symbol_resolver/comments/formats/__init__.py` … 各形式の import と `ALL_FORMATS` (自動生成。手で編集しない)
- `src/dwarf_symbol_resolver/comments/CATALOG.md` … 形式ごとの判定用の正規表現・parsed の型・サンプル・衝突の一覧

形式は `RegexCommentParser` を継承し、`pattern` (判定・抽出の正規表現。コメント全体に fullmatch) と
`samples` (その形式のサンプルと、期待する parsed) を持つ。
**衝突** = ある形式の `pattern` が、ほかの形式のサンプルに合致すること。誤作動の原因になるので許容しない。

## 手順

作業ディレクトリはリポジトリのルート (`pyproject.toml` のある場所)。`pip install -e .` でインストール済みであること (`dsr-*` コマンドが使える)

1. 集約と検査を実行する

   ```
   python src/dwarf_symbol_resolver/devtools/comment_catalog.py --write
   ```

   - 形式ごとに `OK` / `NG` (自己テストの結果) と、衝突の件数が表示される
   - 自己テストの内容: 自分のサンプルすべてに合致するか、`expected` を書いたサンプルは抽出結果が一致するか、サンプルが 1 件以上あるか
   - 終了コード 1 = 自己テストの失敗、または衝突がある

2. 問題があれば利用者に報告する (勝手に直さない)
   - 自己テストの失敗: どの形式の、どのサンプルで、何が違ったか
   - 衝突: どの形式の pattern が、どの形式のどのサンプルに合致したか。
     両方の形式のサンプルを並べて違いを示し、回避できる特徴 (コメント記号、先頭の記号、キーワードの有無など) と
     pattern の更新案を添えて、どちらの形式をどう直すかを利用者に判断してもらう
   - 判断を受けて形式のモジュールを直したら、手順 1 をやり直す

3. 結果を伝える
   - 登録されている形式の一覧 (クラス名、モジュール、parsed の型、サンプル数)
   - `CATALOG.md` へのリンク
   - 衝突・自己テストの結果

## 注意

- `formats/__init__.py` は必ずこのスキル (`src/dwarf_symbol_resolver/devtools/comment_catalog.py --write`) で生成する。
  形式のモジュールを追加・削除・改名したときも、手で import を書き足さずに再生成する
- `ALL_FORMATS` の順序はモジュール名順で、優先度ではない。優先度は利用者が `SymbolResolver` に渡すパーサの順序で決める
- 形式のファイル名の先頭が `_` のものは集約の対象外 (作業中の下書きなどに使える)
