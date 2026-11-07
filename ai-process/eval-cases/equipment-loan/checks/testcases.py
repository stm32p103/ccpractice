#!/usr/bin/env python3
"""テストケース一覧（test-cases.yaml）の確認と、テストコードとの突き合わせ。LLMは使わない。

人はテストコードではなく、この一覧（と、ここで機械が挙げた食い違い）を見て判断する（D07）。

  testcases.py validate   --cases out/test-cases.yaml --reqs REQ-001,... [--md review.md]
      形式・ID重複・要件IDの網羅を確かめ、人が読む表を作る
  testcases.py crosscheck --cases out/test-cases.yaml --tests out/tests [--md review.md]
      一覧の各ケースに対応するテスト（@pytest.mark.tc("TC-xxx")）があるか、
      一覧の期待ステータスがテストの assert に現れるかを確かめる

一覧の形式:
  cases:
    - id: TC-001
      req: [REQ-001]
      given: 前提（今日の日付、備品の状態など）
      when: 操作
      then: { status: 201, check: 確かめる内容 }   # status は数値か数値の配列
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

import yaml

TC_ID = re.compile(r"^TC-\d{3}$")


def load_cases(path: Path) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    if not path.exists():
        return [], [f"{path} が無い"]
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return [], [f"YAMLとして読めない: {e}"]
    cases = doc.get("cases")
    if not isinstance(cases, list):
        return [], ["cases が配列でない"]
    seen = set()
    for i, c in enumerate(cases):
        where = f"cases[{i}]"
        if not isinstance(c, dict):
            errors.append(f"{where} が辞書でない")
            continue
        cid = c.get("id")
        if not (isinstance(cid, str) and TC_ID.match(cid)):
            errors.append(f"{where}.id が TC-000 形式でない: {cid}")
        elif cid in seen:
            errors.append(f"{cid} が重複")
        seen.add(cid)
        for k in ("req", "given", "when", "then"):
            if k not in c:
                errors.append(f"{cid or where} に {k} が無い")
        st = (c.get("then") or {}).get("status") if isinstance(c.get("then"), dict) else None
        if st is None or not all(isinstance(x, int) for x in (st if isinstance(st, list) else [st])):
            errors.append(f"{cid or where} の then.status が数値（または数値の配列）でない")
    return [c for c in cases if isinstance(c, dict)], errors


def statuses(c: dict) -> list[int]:
    st = (c.get("then") or {}).get("status")
    return st if isinstance(st, list) else [st]


def table(cases: list[dict]) -> str:
    rows = ["| ID | 要件 | 前提 | 操作 | 期待 | 確かめる内容 |", "|---|---|---|---|---|---|"]
    for c in cases:
        then = c.get("then") or {}
        rows.append("| {} | {} | {} | {} | {} | {} |".format(
            c.get("id"), ", ".join(c.get("req") or []), cell(c.get("given")), cell(c.get("when")),
            "/".join(map(str, statuses(c))), cell(then.get("check", ""))))
    return "\n".join(rows)


def cell(x) -> str:
    return str(x or "").replace("|", "／").replace("\n", " ")


def validate(a) -> dict:
    cases, errors = load_cases(a.cases)
    wanted = [r for r in a.reqs.split(",") if r]
    covered = {r for c in cases for r in (c.get("req") or [])}
    missing = [r for r in wanted if r not in covered]
    res = {"checker": "testcases.validate", "list_ok": not errors, "list_errors": errors,
           "n_cases": len(cases), "list_req_missing": missing}
    if a.md:
        md = ["## テストケース一覧（人が確認する対象）", "", table(cases), ""]
        md += ["### 機械が挙げた点", ""]
        md += [f"- 形式: {e}" for e in errors] + [f"- 要件の漏れ: {r} に対応するケースが無い" for r in missing]
        if not errors and not missing:
            md.append("- なし")
        append(a.md, md)
    return res


class TestScan(ast.NodeVisitor):
    """テスト関数ごとに、付いている tc マーカーと、assert に出てくる整数（ステータス候補）を集める。"""

    def __init__(self):
        self.tests: list[dict] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if not node.name.startswith("test"):
            return
        tcs = []
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tc":
                tcs += [x.value for x in d.args if isinstance(x, ast.Constant) and isinstance(x.value, str)]
            if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "parametrize":
                # parametrize 内の pytest.param(..., marks=pytest.mark.tc("TC-xxx")) も拾う
                for sub in ast.walk(d):
                    if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "tc":
                        tcs += [x.value for x in sub.args if isinstance(x, ast.Constant)]
        nums = set()
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Assert, ast.Compare)):
                for n in ast.walk(sub):
                    if isinstance(n, ast.Constant) and isinstance(n.value, int) and 100 <= n.value <= 599:
                        nums.add(n.value)
        for d in node.decorator_list:  # parametrize の値にステータスを書く書き方もある
            for n in ast.walk(d):
                if isinstance(n, ast.Constant) and isinstance(n.value, int) and 100 <= n.value <= 599:
                    nums.add(n.value)
        self.tests.append({"name": node.name, "tcs": tcs, "statuses": sorted(nums)})


def crosscheck(a) -> dict:
    cases, errors = load_cases(a.cases)
    scan = TestScan()
    for p in sorted(a.tests.glob("test_*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            errors.append(f"{p.name} を解析できない: {e}")
            continue
        for t in ast.walk(tree):
            if isinstance(t, ast.FunctionDef):
                scan.visit_FunctionDef(t)
    by_tc: dict[str, list[dict]] = {}
    for t in scan.tests:
        for tc in t["tcs"]:
            by_tc.setdefault(tc, []).append(t)
    listed = {c.get("id") for c in cases}
    no_test = [c["id"] for c in cases if c.get("id") not in by_tc]
    status_mismatch = []
    for c in cases:
        tests = by_tc.get(c.get("id"), [])
        found = {s for t in tests for s in t["statuses"]}
        lost = [s for s in statuses(c) if tests and s not in found]
        if lost:
            status_mismatch.append({"tc": c["id"], "expected": statuses(c), "found_in_tests": sorted(found)})
    not_listed = sorted(set(by_tc) - listed)
    untagged = [t["name"] for t in scan.tests if not t["tcs"]]
    res = {"checker": "testcases.crosscheck", "cross_ok": not (no_test or status_mismatch or not_listed),
           "tc_without_test": no_test, "status_mismatch": status_mismatch,
           "tests_with_unlisted_tc": not_listed, "tests_without_tc": untagged, "parse_errors": errors}
    if a.md:
        md = ["## 一覧とテストコードの突き合わせ（機械が挙げた点）", ""]
        md += [f"- {x}: 一覧にあるが、対応するテストが無い" for x in no_test]
        md += [f"- {m['tc']}: 一覧の期待 {m['expected']} がテストの assert に見当たらない（テスト内の値: {m['found_in_tests']}）"
               for m in status_mismatch]
        md += [f"- {x}: テストにあるが一覧に無い（承認していないケース）" for x in not_listed]
        md += [f"- {x}: tc マーカーが無いテスト" for x in untagged]
        md += [f"- {x}" for x in errors]
        if len(md) == 2:
            md.append("- なし")
        append(a.md, md)
    return res


def append(path: Path, lines: list[str]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("--cases", type=Path, required=True)
    v.add_argument("--reqs", required=True); v.add_argument("--md", type=Path)
    c = sub.add_parser("crosscheck"); c.add_argument("--cases", type=Path, required=True)
    c.add_argument("--tests", type=Path, required=True); c.add_argument("--md", type=Path)
    a = ap.parse_args()
    res = validate(a) if a.cmd == "validate" else crosscheck(a)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
