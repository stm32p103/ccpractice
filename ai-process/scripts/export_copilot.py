#!/usr/bin/env python3
"""体制を GitHub Copilot（VS Code）が読む形に書き出す（D14）。

  export_copilot.py --target <書き出し先のリポジトリのルート> [--skills a,b] [--dry-run]

- skills/<name>/      → <target>/.github/skills/<name>/          （そのままコピー）
- agents/<name>.md    → <target>/.github/agents/<name>.agent.md  （frontmatter を Copilot 向けに変換）
- <target>/.github/ai-process.lock に、書き出した体制の版と元のコミットを記録する

ツール名やフィールド名は Copilot の版で変わることがある。書き出し後、VS Code の Agent Debug Log や
回答の References 欄で、スキル・エージェントが読み込まれていることを確かめること。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# Claude Code のツール名 → Copilot のツール名（要確認。合わないものは書き出し時に警告する）
TOOL_MAP = {"Read": "read", "Grep": "search", "Glob": "search", "Write": "edit", "Edit": "edit", "Bash": "execute"}
DROP_KEYS = {"maxTurns"}   # Copilot の定義に無い項目。本文に注記として残す


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm) or {}, body.lstrip("\n")


def convert_agent(src: Path) -> tuple[str, list[str]]:
    fm, body = split_frontmatter(src.read_text(encoding="utf-8"))
    warnings, notes = [], []
    tools = fm.get("tools")
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    if tools:
        mapped = []
        for t in tools:
            if t not in TOOL_MAP:
                warnings.append(f"{src.name}: ツール {t} の対応先が不明")
                continue
            if TOOL_MAP[t] not in mapped:
                mapped.append(TOOL_MAP[t])
        fm["tools"] = mapped
    for k in DROP_KEYS & set(fm):
        notes.append(f"- 元の定義の {k}: {fm.pop(k)}（Copilot では設定で制御する）")
    head = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    extra = ("\n\n## 移植時の注記\n" + "\n".join(notes)) if notes else ""
    return f"---\n{head}\n---\n{body.rstrip()}{extra}\n", warnings


def git_rev() -> str | None:
    p = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return p.stdout.strip() or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=Path, required=True)
    ap.add_argument("--skills", default="", help="書き出すスキル名（カンマ区切り）。省略時はすべて")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    version = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    names = [x for x in a.skills.split(",") if x] or sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir())
    gh = a.target / ".github"
    warnings: list[str] = []
    for name in names:
        dst = gh / "skills" / name
        print(f"skill  {name} → {dst}")
        if not a.dry_run:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(ROOT / "skills" / name, dst)
    for src in sorted((ROOT / "agents").glob("*.md")):
        text, w = convert_agent(src)
        warnings += w
        dst = gh / "agents" / f"{src.stem}.agent.md"
        print(f"agent  {src.name} → {dst}")
        if not a.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
    lock = {"process": "ai-process", "version": version, "source_commit": git_rev(), "skills": names}
    if not a.dry_run:
        (gh / "ai-process.lock").write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(lock, ensure_ascii=False))
    for w in warnings:
        print("警告:", w, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
