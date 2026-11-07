#!/usr/bin/env python3
"""この題材の判定スクリプトが正しく働くかを確かめる（評価の仕組み自体のテスト）。LLMは使わない。

- 模範のテスト: 参照実装で通り、全ミュータントを検出し、一覧との突き合わせも通る
- 弱いテスト  : 参照実装では通るが、検出率が低い
- 参照の契約 v2 は v1 に対して後方互換。逆向きは互換性が壊れていると判定される
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE.parent
CHK = SUITE / "checks"
FIX = SUITE / "fixtures"
ALL_M = ("m01_no_conflict_check,m02_due_upper_15,m03_due_same_day_ok,m04_return_not_loaned_ok,m05_status_unknown_200,"
         "m06_overdue_includes_due,m07_status_keeps_borrower,m08_extend_twice,m09_extend_by_other,m10_extend_upper_8")
ALL_R = ",".join(f"REQ-00{i}" for i in range(1, 10))


def run(*args) -> dict:
    p = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)
    return json.loads(p.stdout)


def main() -> int:
    checks = []
    g = run(CHK / "check_tests.py", "--tests", HERE / "golden_tests", "--mutants", ALL_M, "--reqs", ALL_R)
    checks.append(("模範テストが参照実装で通る", g["reference_pass"]))
    checks.append(("模範テストが全ミュータントを検出", g["kill_rate"] == 1.0))
    w = run(CHK / "check_tests.py", "--tests", HERE / "weak_tests", "--mutants", ALL_M, "--reqs", ALL_R)
    checks.append(("弱いテストは参照実装で通る", w["reference_pass"]))
    checks.append(("弱いテストの検出率は低い", w["kill_rate"] < 0.3))
    v = run(CHK / "testcases.py", "validate", "--cases", HERE / "golden_tests/test-cases.yaml", "--reqs", ALL_R)
    checks.append(("模範の一覧が形式どおりで要件を網羅", v["list_ok"] and not v["list_req_missing"]))
    c = run(CHK / "testcases.py", "crosscheck", "--cases", HERE / "golden_tests/test-cases.yaml", "--tests", HERE / "golden_tests")
    checks.append(("模範の一覧とテストが一致", c["cross_ok"]))
    c2 = run(CHK / "testcases.py", "crosscheck", "--cases", HERE / "golden_tests/test-cases.yaml", "--tests", HERE / "weak_tests")
    checks.append(("一覧と弱いテストの食い違いを検出", not c2["cross_ok"] and len(c2["tc_without_test"]) >= 7))
    o = run(CHK / "check_openapi.py", "--contract", FIX / "openapi_v2.yaml", "--requirements", FIX / "requirements_v2.md",
            "--baseline", FIX / "openapi_v1.yaml", "--expect-status", "REQ-002=409;REQ-009=403")
    checks.append(("契約v2はv1と互換", o["valid"] and not o["breaking_changes"] and not o["status_ng"]))
    o2 = run(CHK / "check_openapi.py", "--contract", FIX / "openapi_v1.yaml", "--requirements", FIX / "requirements_v2.md",
             "--baseline", FIX / "openapi_v2.yaml")
    checks.append(("契約v1→v2の逆向きは互換性の破壊を検出", bool(o2["breaking_changes"]) and o2["req_missing"] == ["REQ-009"]))

    for name, ok in checks:
        print(("OK  " if ok else "NG  ") + name)
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
