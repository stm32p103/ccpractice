#!/usr/bin/env python3
"""Spec Kitの進み具合を一覧にするスクリプト(相談スキル用)。

使い方(リポジトリのルートで実行):
    python .github/skills/speckit-team-consult/scripts/speckit_status.py
    python .github/skills/speckit-team-consult/scripts/speckit_status.py --feature 002-equipment-core

標準ライブラリだけで動きます。ファイルは読むだけで、書き換えません。
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

SHARED_FILES = {
    "進め方ガイド": "docs/spec-kit-team-guide.md",
    "constitution": ".specify/memory/constitution.md",
    "用語集": "docs/glossary.md",
    "ドメインモデル": "docs/domain/model.md",
    "機能マップ": "docs/feature-map.md",
    "API契約": "contracts",
}

TASK_RE = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.*)$")
HOLD_RE = re.compile(r"保留")


def find_root(start: Path) -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return start


def current_branch(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or "(不明)"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "(gitなし)"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def task_progress(tasks_md: Path) -> tuple[int, int, list[str]]:
    done = total = 0
    held: list[str] = []
    for line in read_text(tasks_md).splitlines():
        m = TASK_RE.match(line)
        if not m:
            continue
        total += 1
        if m.group(1).lower() == "x":
            done += 1
        elif HOLD_RE.search(m.group(2)):
            held.append(m.group(2).strip())
    return done, total, held


def feature_status(feature_dir: Path) -> dict:
    spec = feature_dir / "spec.md"
    plan = feature_dir / "plan.md"
    tasks = feature_dir / "tasks.md"
    spec_text = read_text(spec)

    info = {
        "name": feature_dir.name,
        "spec": spec.exists(),
        "clarified": "## Clarifications" in spec_text,
        "needs_clarification": spec_text.count("[NEEDS CLARIFICATION"),
        "plan": plan.exists(),
        "contracts": (feature_dir / "contracts").exists(),
        "checklists": (feature_dir / "checklists").exists(),
        "tasks": tasks.exists(),
        "done": 0,
        "total": 0,
        "held": [],
    }
    if info["tasks"]:
        info["done"], info["total"], info["held"] = task_progress(tasks)

    if not info["spec"]:
        stage = "未着手(specなし)"
    elif not info["plan"]:
        stage = "specify・clarify" + ("(clarify済み)" if info["clarified"] else "")
    elif not info["tasks"]:
        stage = "plan"
    elif info["total"] == 0:
        stage = "tasks(タスク未記入)"
    elif info["done"] == 0:
        stage = "tasks・analyze(実装前)"
    elif info["done"] < info["total"]:
        stage = "implement(実装中)"
    else:
        stage = "受入待ち・完了(全タスク完了)"
    info["stage"] = stage
    return info


def mark(flag: bool) -> str:
    return "あり" if flag else "なし"


def main() -> None:
    parser = argparse.ArgumentParser(description="Spec Kitの進み具合を表示する")
    parser.add_argument("--feature", help="対象の機能フォルダ名(例: 002-equipment-core)")
    parser.add_argument("--root", help="リポジトリのルート(省略時はgitから判定)")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else find_root(Path.cwd())
    print(f"# Spec Kit 進み具合\n\n- ルート: `{root}`\n- 現在のブランチ: `{current_branch(root)}`\n")

    print("## 共通部・ルール")
    for label, rel in SHARED_FILES.items():
        print(f"- {label}: {mark((root / rel).exists())}(`{rel}`)")
    ideas = root / "ideas"
    n_ideas = len([p for p in ideas.glob("*.md")]) if ideas.exists() else 0
    print(f"- アイディア置き場: {n_ideas}件(`ideas/`)\n")

    specs_dir = root / "specs"
    if not specs_dir.exists():
        print("## 機能\n- `specs/` がありません(Spec Kitの機能はまだ作られていません)")
        return

    features = sorted(p for p in specs_dir.iterdir() if p.is_dir())
    if args.feature:
        features = [p for p in features if p.name == args.feature]
        if not features:
            print(f"## 機能\n- `{args.feature}` が見つかりません")
            return

    print("## 機能")
    print("| 機能 | 推定段階 | spec | 要確認箇所 | plan | contracts | checklists | タスク進捗 | 保留 |")
    print("|---|---|---|---|---|---|---|---|---|")
    details = []
    for f in features:
        s = feature_status(f)
        progress = f"{s['done']}/{s['total']}" if s["tasks"] else "-"
        print(
            f"| {s['name']} | {s['stage']} | {mark(s['spec'])} | {s['needs_clarification']} "
            f"| {mark(s['plan'])} | {mark(s['contracts'])} | {mark(s['checklists'])} "
            f"| {progress} | {len(s['held'])} |"
        )
        if s["held"]:
            details.append((s["name"], s["held"]))

    if details:
        print("\n## 保留中のタスク")
        for name, held in details:
            print(f"- {name}")
            for h in held:
                print(f"  - {h}")

    print(
        "\n※ 推定段階はファイルの有無とタスクのチェック状況から機械的に判定したものです。"
        "実際の段階は相談者に確認してください。"
    )


if __name__ == "__main__":
    main()
