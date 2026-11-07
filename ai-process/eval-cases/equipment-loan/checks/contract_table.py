#!/usr/bin/env python3
"""OpenAPI 契約を、人が読む表にする（D09）。LLMは使わない。

人は YAML を読まずに、この表で「操作の切り方」「要件との対応」「エラーの使い分け」を確かめる。

  contract_table.py --contract out/openapi.yaml [--baseline in/openapi_current.yaml] --md review.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

METHODS = ("get", "post", "put", "patch", "delete")


def ops(spec: dict) -> dict[tuple[str, str], dict]:
    out = {}
    for path, item in (spec.get("paths") or {}).items():
        for m in METHODS:
            if isinstance((item or {}).get(m), dict):
                out[(path, m)] = item[m]
    return out


def resolve(spec: dict, node):
    while isinstance(node, dict) and "$ref" in node and node["$ref"].startswith("#/"):
        cur = spec
        for part in node["$ref"][2:].split("/"):
            cur = cur.get(part, {})
        node = cur
    return node


def describe_responses(spec: dict, op: dict) -> str:
    parts = []
    for code, r in (op.get("responses") or {}).items():
        desc = (resolve(spec, r) or {}).get("description", "")
        parts.append(f"{code} {desc}".strip())
    return "<br>".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--md", type=Path, required=True)
    a = ap.parse_args()
    if not a.contract.exists():
        print(json.dumps({"checker": "contract_table", "table_ok": False}))
        return 0
    spec = yaml.safe_load(a.contract.read_text(encoding="utf-8"))
    base = ops(yaml.safe_load(a.baseline.read_text(encoding="utf-8"))) if a.baseline else {}
    lines = ["## 契約の一覧（人が確認する対象）", "",
             "| 変更 | 操作 | 要件 | 概要 | 応答 |", "|---|---|---|---|---|"]
    for (path, m), op in ops(spec).items():
        mark = "" if not a.baseline else ("追加" if (path, m) not in base else "")
        lines.append(f"| {mark} | {m.upper()} {path} | {', '.join(op.get('x-req-ids') or [])} | "
                     f"{op.get('summary', '')} | {describe_responses(spec, op)} |")
    with a.md.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")
    print(json.dumps({"checker": "contract_table", "table_ok": True, "n_operations": len(ops(spec))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
