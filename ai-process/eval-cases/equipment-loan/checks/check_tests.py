#!/usr/bin/env python3
"""B系（契約→テスト）の判定スクリプト。LLMは使わない。

1. 生成テストを、参照実装に対して実行する → 全部通るべき（通らない＝契約に無いことを決めつけている等）
2. ミュータント（1か所だけ壊した実装）ごとに実行する → 失敗すれば「検出できた」
3. @pytest.mark.req("REQ-xxx") の付与状況から、要件の網羅を数える

使い方:
  check_tests.py --tests <テストのディレクトリ> --mutants m01,m02,... --reqs REQ-001,... [--out score.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
FIX = KIT / "fixtures"
REQ_MARK = re.compile(r"""mark\.req\(([^)]*)\)""")
REQ_ID = re.compile(r"REQ-\d{3}")


def run_pytest(workdir: Path, mutant: str | None) -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("MUTANT", None)
    if mutant:
        env["MUTANT"] = mutant
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(workdir), "tests"],
        cwd=workdir, env=env, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout[-3000:] + p.stderr[-1000:]


def count_tests(workdir: Path) -> int:
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider", "tests"],
                       cwd=workdir, capture_output=True, text=True, timeout=120)
    return sum(1 for line in p.stdout.splitlines() if "::" in line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", required=True, type=Path)
    ap.add_argument("--mutants", required=True)
    ap.add_argument("--reqs", required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    test_files = sorted(a.tests.glob("test_*.py"))
    result: dict = {"checker": "check_tests", "test_files": [str(p) for p in test_files]}
    if not test_files:
        result.update(status="ng", error="test_*.py が見つからない")
        return finish(result, a.out)

    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        shutil.copytree(FIX / "app", w / "app")
        shutil.copy(FIX / "conftest.py", w / "conftest.py")  # 生成側のconftestは使わず、約束どおりのものに差し替える
        (w / "tests").mkdir()
        for p in test_files:
            shutil.copy(p, w / "tests" / p.name)

        result["n_tests"] = count_tests(w)
        rc, log = run_pytest(w, None)
        result["reference_pass"] = rc == 0
        if rc != 0:
            result["reference_log"] = log

        killed, survived = [], []
        for m in [x for x in a.mutants.split(",") if x]:
            rc_m, _ = run_pytest(w, m)
            (killed if rc_m != 0 else survived).append(m)
        total = len(killed) + len(survived)
        result.update(killed=killed, survived=survived,
                      kill_rate=round(len(killed) / total, 3) if total else None)

    marked: set[str] = set()
    for p in test_files:
        for args in REQ_MARK.findall(p.read_text(encoding="utf-8")):
            marked.update(REQ_ID.findall(args))
    wanted = [r for r in a.reqs.split(",") if r]
    result["req_marked"] = sorted(marked)
    result["req_missing"] = [r for r in wanted if r not in marked]
    result["req_coverage"] = round((len(wanted) - len(result["req_missing"])) / len(wanted), 3) if wanted else None
    # 参照実装で落ちるなら、検出率は意味を持たない（何でも落ちるテストは全ミュータントを「検出」する）
    if not result["reference_pass"]:
        result["kill_rate_note"] = "参照実装で失敗しているため、kill_rate は参考値"
    return finish(result, a.out)


def finish(result: dict, out: Path | None) -> int:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if out:
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
