#!/usr/bin/env python3
"""Claude アプリにアップロードするスキルの zip を作る。正本はリポジトリ。アプリ側では直接編集しない。

  pack_skill.py <スキル名> [<スキル名> ...]   → ai-process/dist/<スキル名>-<版>.zip
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    version = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for name in sys.argv[1:]:
        src = ROOT / "skills" / name
        if not (src / "SKILL.md").exists():
            print(f"{src}/SKILL.md が無い", file=sys.stderr)
            return 1
        out = dist / f"{name}-{version}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(src.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    z.write(p, Path(name) / p.relative_to(src))   # zip の中は <スキル名>/SKILL.md の形
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
