#!/usr/bin/env python3
"""どの題材でも使う判定（LLMは使わない）。

  common_checks.py questions --file out/open-questions.md --reqs REQ-003,REQ-008
      未決事項のファイルがあり、指定の要件IDが書かれているか
  common_checks.py unchanged --pair in/a.py=out/a.py [--pair ...]
      渡したファイルが変更されずに残っているか
  common_checks.py result --file out/result.json --version 0.2.0
      返答の標準形（status, outputs, key_points, unresolved）と、体制の版が書かれているか
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("questions"); q.add_argument("--file", type=Path, required=True); q.add_argument("--reqs", required=True)
    u = sub.add_parser("unchanged"); u.add_argument("--pair", action="append", required=True)
    r = sub.add_parser("result"); r.add_argument("--file", type=Path, required=True); r.add_argument("--version", required=True)
    a = ap.parse_args()

    if a.cmd == "questions":
        text = a.file.read_text(encoding="utf-8") if a.file.exists() else ""
        res = {"questions_file": a.file.exists(),
               "questions_missing": [x for x in a.reqs.split(",") if x and x not in text]}
    elif a.cmd == "unchanged":
        res = {"unchanged_ok": all(sha(Path(x)) is not None and sha(Path(x)) == sha(Path(y))
                                   for x, y in (p.split("=", 1) for p in a.pair))}
    else:
        try:
            d = json.loads(a.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            d = None
        keys = {"status", "outputs", "key_points", "unresolved"}
        res = {"result_ok": isinstance(d, dict) and keys <= set(d),
               "result_version_ok": isinstance(d, dict) and d.get("process_version") == a.version,
               "result_model": d.get("model") if isinstance(d, dict) else None}
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
