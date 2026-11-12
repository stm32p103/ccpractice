#!/usr/bin/env python3
"""knowledge/ の frontmatter から public/index.md の知識一覧を作る（docs/knowledge-format.md）。

  build_public_index.py <ドメインのプラグインのルート> [--check]

- knowledge/*.md の frontmatter を読み、必須項目と値を確かめる（`_` で始まるファイルはひな形として飛ばす）
- public/index.md の BEGIN/END の印の間だけを書き換える。扱う範囲・扱わない範囲など、人が書いた部分は残す
- public/index.md が無ければ templates/domain/public/index.md から作る
- ドラフトの知識も載せ、状態の欄に「ドラフト」と出す
- --check: 書き込まず、一覧が古いか書式の誤りがあれば終了コード1を返す（CI用）

LLMは使わない。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "domain" / "public" / "index.md"
REQUIRED = ["id", "title", "summary", "applies_to", "sources", "owner", "review", "updated"]
REVIEW_STATES = {"draft": "**ドラフト**", "reviewed": "レビュー済み"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BEGIN_RE = re.compile(r"^<!-- BEGIN knowledge-list.*-->$", re.M)
END_RE = re.compile(r"^<!-- END knowledge-list -->$", re.M)


def read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("frontmatter がない")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("frontmatter が閉じていない")
    fm = yaml.safe_load(parts[1]) or {}
    if not isinstance(fm, dict):
        raise ValueError("frontmatter が辞書になっていない")
    return fm


def validate(path: Path, fm: dict) -> list[str]:
    errs = [f"{k} がない" for k in REQUIRED if fm.get(k) in (None, "", [])]
    if errs:
        return errs
    if str(fm["id"]) != path.stem:
        errs.append(f"id（{fm['id']}）がファイル名（{path.stem}）と違う")
    if not ID_RE.match(str(fm["id"])):
        errs.append("id は英小文字、数字、ハイフンだけにする")
    if fm["review"] not in REVIEW_STATES:
        errs.append(f"review は {' / '.join(REVIEW_STATES)} のどちらか（今は {fm['review']}）")
    for k in ("applies_to", "sources"):
        if not isinstance(fm[k], list):
            errs.append(f"{k} は配列にする")
    if "\n" in str(fm["summary"]):
        errs.append("summary は1行にする")
    return errs


def cell(v) -> str:
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    return str(v).replace("|", "\\|").replace("\n", " ")


def build_list(items: list[dict]) -> str:
    drafts = sum(1 for fm in items if fm["review"] == "draft")
    lines = [f"全{len(items)}件（うちドラフト{drafts}件。ドラフトはレビュー前の内容を含む）", ""]
    if not items:
        return "\n".join(lines[:1])
    lines += ["| 状態 | id | タイトル | 要約 | 適用範囲 | 更新日 |", "|---|---|---|---|---|---|"]
    for fm in sorted(items, key=lambda f: str(f["id"])):
        link = f"[{fm['id']}](../knowledge/{fm['id']}.md)"
        lines.append("| " + " | ".join([REVIEW_STATES[fm["review"]], link, cell(fm["title"]),
                                       cell(fm["summary"]), cell(fm["applies_to"]), cell(fm["updated"])]) + " |")
    return "\n".join(lines)


def render(index_text: str, body: str) -> str:
    b, e = BEGIN_RE.search(index_text), END_RE.search(index_text)
    if not b or not e or e.start() < b.end():
        raise ValueError("public/index.md に BEGIN/END の印がない（templates/domain/public/index.md を参照）")
    return index_text[: b.end()] + "\n" + body + "\n" + index_text[e.start():]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("domain_root", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    kdir = args.domain_root / "knowledge"
    if not kdir.is_dir():
        print(f"knowledge/ がない: {kdir}（対象が無いので何もしない）")
        return 0

    items, errors = [], []
    for path in sorted(kdir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            fm = read_frontmatter(path)
        except (ValueError, yaml.YAMLError) as ex:
            errors.append(f"{path.name}: {ex}")
            continue
        errs = validate(path, fm)
        if errs:
            errors += [f"{path.name}: {m}" for m in errs]
        else:
            items.append(fm)
    if errors:
        print("書式の誤り:", *errors, sep="\n  ", file=sys.stderr)
        return 1

    index = args.domain_root / "public" / "index.md"
    current = index.read_text(encoding="utf-8") if index.exists() else TEMPLATE.read_text(encoding="utf-8")
    try:
        new = render(current, build_list(items))
    except ValueError as ex:
        print(ex, file=sys.stderr)
        return 1

    if args.check:
        if not index.exists() or new != current:
            print("public/index.md が古い。build_public_index.py を実行する", file=sys.stderr)
            return 1
        print(f"OK（{len(items)}件）")
        return 0

    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(new, encoding="utf-8")
    print(f"{index} を更新した（{len(items)}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
