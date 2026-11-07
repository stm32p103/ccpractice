#!/usr/bin/env python3
"""A系（要件→OpenAPI）の判定スクリプト。LLMは使わない。

確かめること（機械で決まる部分だけ。意味の妥当性はLLM採点と人が見る）
1. OpenAPI 3.x として正しいか（openapi-spec-validator）
2. 要件IDの網羅: 各 operation の x-req-ids に、要件書の全IDが現れるか
3. 要件ごとに必要なエラー応答: 例 REQ-002 → 409。そのIDを持つ operation のどれかに、指定の status があるか
4. （--baseline 指定時）後方互換: 旧契約の path+method・応答コードが残っているか、必須の入力が増えていないか
5. （--questions 指定時）未決事項の記録: 指定の要件IDが未決事項ファイルに書かれているか

使い方:
  check_openapi.py --contract out/openapi.yaml --requirements in/requirements.md
                   [--expect-status 'REQ-002=409;REQ-003=400|422;REQ-006=404']
                   [--baseline in/openapi_v1.yaml] [--questions out/open-questions.md --question-reqs REQ-003,REQ-008]
                   [--out score.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from openapi_spec_validator import validate

REQ_ID = re.compile(r"REQ-\d{3}")
METHODS = {"get", "post", "put", "patch", "delete"}


def operations(spec: dict):
    for path, item in (spec.get("paths") or {}).items():
        for method, op in (item or {}).items():
            if method in METHODS and isinstance(op, dict):
                yield path, method, op


def resolve(spec: dict, node):
    """ローカル $ref を1段ずつたどる（#/components/... のみ）。"""
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return node
        cur = spec
        for part in ref[2:].split("/"):
            cur = cur.get(part, {})
        node = cur
    return node


def required_inputs(spec: dict, op: dict) -> set[str]:
    req = set()
    for p in op.get("parameters", []) or []:
        p = resolve(spec, p)
        if p.get("required"):
            req.add(f"{p.get('in')}:{p.get('name')}")
    body = resolve(spec, op.get("requestBody") or {})
    for ctype, media in (body.get("content") or {}).items():
        schema = resolve(spec, media.get("schema") or {})
        for name in schema.get("required", []) or []:
            req.add(f"body:{name}")
    return req


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True, type=Path)
    ap.add_argument("--requirements", required=True, type=Path)
    ap.add_argument("--expect-status", default="")
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--questions", type=Path)
    ap.add_argument("--question-reqs", default="")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r: dict = {"checker": "check_openapi"}

    if not a.contract.exists():
        r.update(valid=False, error="契約ファイルが無い")
        return finish(r, a.out)
    try:
        spec = yaml.safe_load(a.contract.read_text(encoding="utf-8"))
        validate(spec)
        r["valid"] = True
    except Exception as e:  # noqa: BLE001
        r.update(valid=False, error=f"{type(e).__name__}: {str(e)[:500]}")
        return finish(r, a.out)

    wanted = sorted(set(REQ_ID.findall(a.requirements.read_text(encoding="utf-8"))))
    by_req: dict[str, list[tuple[str, str, dict]]] = {}
    for path, method, op in operations(spec):
        for rid in op.get("x-req-ids", []) or []:
            by_req.setdefault(rid, []).append((path, method, op))
    r["req_missing"] = [x for x in wanted if x not in by_req]
    r["req_coverage"] = round((len(wanted) - len(r["req_missing"])) / len(wanted), 3)
    r["req_unknown"] = sorted(set(by_req) - set(wanted))  # 要件書に無いIDを書いている

    status_ng = []
    for item in [x for x in a.expect_status.split(";") if x.strip()]:
        rid, codes = item.split("=")
        codes = set(codes.split("|"))
        ops = by_req.get(rid.strip(), [])
        if not any(codes & set(map(str, (op.get("responses") or {}).keys())) for _, _, op in ops):
            status_ng.append({"req": rid.strip(), "expected_any_of": sorted(codes)})
    r["status_ng"] = status_ng

    if a.baseline:
        base = yaml.safe_load(a.baseline.read_text(encoding="utf-8"))
        new_ops = {(p, m): op for p, m, op in operations(spec)}
        breaking = []
        for p, m, op in operations(base):
            nop = new_ops.get((p, m))
            if nop is None:
                breaking.append(f"{m.upper()} {p} が消えた")
                continue
            lost = set(map(str, op.get("responses", {}))) - set(map(str, nop.get("responses", {})))
            if lost:
                breaking.append(f"{m.upper()} {p} の応答 {sorted(lost)} が消えた")
            added = required_inputs(spec, nop) - required_inputs(base, op)
            if added:
                breaking.append(f"{m.upper()} {p} に必須入力 {sorted(added)} が増えた")
        r["breaking_changes"] = breaking

    if a.questions:
        want_q = [x for x in a.question_reqs.split(",") if x]
        text = a.questions.read_text(encoding="utf-8") if a.questions.exists() else ""
        r["questions_file"] = a.questions.exists()
        r["questions_missing"] = [x for x in want_q if x not in text]
    return finish(r, a.out)


def finish(r: dict, out: Path | None) -> int:
    text = json.dumps(r, ensure_ascii=False, indent=2)
    if out:
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
