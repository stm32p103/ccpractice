"""新しいコメント形式の候補 (正規表現) を, 利用者の抜粋と既存の形式に対して確認する。

usage:
    dsr-comment-check --pattern "<正規表現>" --excerpt 抜粋1.c [--excerpt 抜粋2.c ...]
                                  [--exclude 既存形式のクラス名] [--flags S]

    --pattern : 候補の正規表現 (コメント全体に fullmatch させる。項目は名前付きグループ (?P<名前>...))
    --excerpt : 利用者が示したソースの抜粋 (コメントを含むコード片。コメントを自動で取り出す)
    --comment : 抜粋ファイルの代わりにコメント文字列を直接指定 (複数可)
    --exclude : 既存形式の pattern を更新する場合の, 更新対象の形式 (自分自身との衝突を除く)
    --flags   : 正規表現のフラグ (S=DOTALL, I=IGNORECASE, M=MULTILINE)

出力 (Markdown):
    1. 抜粋のコメントごとに, 候補が合致したか・名前付きグループの値
    2. 衝突 (a) 既存形式が抜粋のコメントに合致した
    3. 衝突 (b) 候補が既存形式のサンプルに合致した
終了コード: 衝突があれば 1, 抜粋のコメントに 1 件も合致しなければ 2, それ以外 0
"""
import argparse
import os
import re
import sys

from dwarf_symbol_resolver.comments import Sample, catalog, scan_comments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--excerpt", action="append", default=[])
    ap.add_argument("--comment", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--flags", default="")
    a = ap.parse_args()

    flags = 0
    for ch in a.flags.upper():
        flags |= {"S": re.S, "I": re.I, "M": re.M}[ch]
    pattern = re.compile(a.pattern, flags)

    comments = [Sample(c, source="--comment") for c in a.comment]
    for path in a.excerpt:
        with open(path, encoding="utf-8", errors="replace") as f:
            for c in scan_comments(f.read()):
                comments.append(Sample(c.text, source=f"{os.path.basename(path)}:{c.start}"))

    formats = catalog.discover()
    r = catalog.check_candidate(pattern, comments, formats, tuple(a.exclude))

    print("## 候補の正規表現", "", "```regex", pattern.pattern, "```", "", sep="\n")
    print("## 抜粋のコメントへの合致", "", "| 出典 | コメント | 合致 | 抽出された項目 |", "|---|---|---|---|", sep="\n")
    for s, g in r["matches"]:
        groups = ", ".join(f"{k}={v!r}" for k, v in g.items()) if g else "-"
        print(f"| {s.source} | `{s.comment}` | {'○' if g is not None else '×'} | {groups} |".replace("\n", "⏎"))
    print("\n## 衝突 (a): 既存形式が抜粋のコメントに合致\n")
    print("\n".join(f"- `{c.pattern_owner}` が `{c.comment}` に合致" for c in r["taken"]) or "- なし")
    print("\n## 衝突 (b): 候補が既存形式のサンプルに合致\n")
    print("\n".join(f"- 候補が `{c.sample_owner}` のサンプル `{c.comment}` に合致" for c in r["intrudes"]) or "- なし")
    print(f"\n登録済みの形式: {', '.join(f.name for f in formats if f.name not in a.exclude) or 'なし'}")

    if r["taken"] or r["intrudes"]:
        sys.exit(1)
    if not any(g is not None for _, g in r["matches"]):
        sys.exit(2)


if __name__ == "__main__":
    main()
