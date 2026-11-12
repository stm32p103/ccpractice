#!/usr/bin/env python3
"""build_public_index.py の自己テスト。一時ディレクトリにドメインを作って確かめる。

  python3 ai-process/scripts/selftest_build_public_index.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "build_public_index.py"
TEMPLATES = HERE.parent / "templates" / "domain"

KNOWLEDGE = {
    "x-rule.md": """---
id: x-rule
title: 通信Xの決まり
summary: 通信Xで、受け取りが途絶えたときの扱い
applies_to: [製品A v2.x]
sources: [資料P.xlsx#シートS!行10]
owner: 担当者
review: reviewed
updated: 2026-11-12
---
本文
""",
    "y-quirks.md": """---
id: y-quirks
title: 装置Yの癖
summary: 手順書に無い注意点
applies_to: [共通]
sources: [記録Q.pdf p.4]
owner: 担当者
review: draft
updated: 2026-11-12
---
本文
""",
}


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def main() -> int:
    failures = []

    def expect(cond: bool, msg: str) -> None:
        print(("OK  " if cond else "NG  ") + msg)
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory() as tmp:
        dom = Path(tmp) / "domain-a"
        shutil.copytree(TEMPLATES, dom)
        idx = dom / "public" / "index.md"
        idx.write_text(idx.read_text(encoding="utf-8").replace("(このドメインで扱うこと)", "人が書いた範囲"), encoding="utf-8")
        for name, text in KNOWLEDGE.items():
            (dom / "knowledge" / name).write_text(text, encoding="utf-8")

        expect(run(str(dom), "--check").returncode == 1, "生成前は --check が古いと判定する")
        expect(run(str(dom)).returncode == 0, "生成できる")
        out = idx.read_text(encoding="utf-8")
        expect("人が書いた範囲" in out, "人が書いた部分を残す")
        expect("全2件（うちドラフト1件" in out, "件数とドラフトの件数を出す")
        expect("| **ドラフト** | [y-quirks]" in out, "ドラフトを明示して載せる")
        expect("| レビュー済み | [x-rule]" in out, "レビュー済みを載せる")
        expect("_template" not in out, "ひな形を載せない")
        expect(run(str(dom), "--check").returncode == 0, "生成後は --check が通る")
        expect(run(str(dom)).returncode == 0 and idx.read_text(encoding="utf-8") == out, "2回目の生成で変わらない")

        (dom / "knowledge" / "bad.md").write_text("---\nid: other\ntitle: t\n---\n", encoding="utf-8")
        r = run(str(dom))
        expect(r.returncode == 1 and "summary がない" in r.stderr, "必須項目の抜けを止める")
        (dom / "knowledge" / "bad.md").unlink()

        expect(run(str(Path(tmp) / "none")).returncode == 0, "knowledge/ が無ければ何もしない")

    print(f"\n{'失敗 ' + str(len(failures)) + '件' if failures else 'すべて成功'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
