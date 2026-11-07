#!/usr/bin/env python3
"""評価の仕組み（共通部）。題材に依存しない。LLMは呼ばない（LLMの実行は人が行う）。

  kit.py prepare <case> --suite <題材> --variant noskill|skill [--env claude|copilot] [--trials 3]  実行用の場所を作る
  kit.py next    <run_id>      今の段階で実行するコマンドを表示する
  kit.py review  <run_id>      ゲートのある段階のあとに、人が見る review_<段階>.md を作る
  kit.py approve <run_id>      ゲートを承認して次の段階へ進める（差し戻すなら、同じ段階をもう一度実行して review する）
  kit.py score   <run_id ...> | --all   最後の判定（score.json）と、人が見る review.md を作る
  kit.py summarize             eval/results/summary.md に集計する

題材は eval-cases/<題材>/cases.yaml に書く（書き方はそのファイルの先頭と eval/README.md）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parent            # ai-process/eval
ROOT = KIT.parent                                # ai-process
SUITES = ROOT / "eval-cases"
RUNS = KIT / "runs"
HIDDEN = RUNS / "_hidden"
INDEX = RUNS / "index.csv"
RESULTS = KIT / "results"
FIELDS = ["run_id", "suite", "case", "variant", "env", "trial", "process_version", "created"]
ENVS = ["claude", "copilot"]   # 生成役を動かす環境（D19）
PLUGIN = "ai-process@ccpractice"
# 評価中はプラグインを無効にする（有効だと「スキル無し」にも評価対象のスキルが混ざる）。オプション名は最新のドキュメントで確認すること
NO_PLUGIN = f"--settings '{{\"enabledPlugins\": {{\"{PLUGIN}\": false}}}}'"


def process_version() -> str:
    return json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]


def load_suite(name: str) -> dict:
    return yaml.safe_load((SUITES / name / "cases.yaml").read_text(encoding="utf-8"))


def index() -> dict[str, dict]:
    if not INDEX.exists():
        return {}
    with INDEX.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["env"] = r.get("env") or "claude"   # env 列が無かった頃（0.2.0）の行は Claude Code とみなす
    return {r["run_id"]: r for r in rows}


def migrate_index() -> None:
    """0.2.0 の index.csv（env 列なし）を、今の列に書き直す。"""
    if not INDEX.exists():
        return
    with INDEX.open(encoding="utf-8") as f:
        header = next(csv.reader(f), [])
    if header == FIELDS:
        return
    rows = list(index().values())
    with INDEX.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in FIELDS} for r in rows)


def state(run: Path) -> dict:
    return json.loads((run / "state.json").read_text(encoding="utf-8"))


def save_state(run: Path, st: dict) -> None:
    (run / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def ctx(rid: str) -> tuple[dict, dict, dict, Path]:
    row = index()[rid]
    suite = load_suite(row["suite"])
    return row, suite, suite["cases"][row["case"]], RUNS / rid


def fill(arg: str, **kw) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(kw.get(m.group(1), m.group(0))), arg)


def run_cmds(cmds: list, suite_dir: Path, **kw) -> dict:
    merged: dict = {}
    for cmd in cmds or []:
        args = [fill(str(x), **kw) for x in cmd]
        first = args[0] if Path(args[0]).is_absolute() else str(suite_dir / args[0])
        argv = [sys.executable, first, *args[1:]] if first.endswith(".py") else [first, *args[1:]]
        p = subprocess.run(argv, capture_output=True, text=True, cwd=suite_dir)
        try:
            merged.update(json.loads(p.stdout))
        except json.JSONDecodeError:
            merged.setdefault("errors", []).append({"cmd": args[:2], "stderr": p.stderr[-1500:]})
    return merged


# ---------------------------------------------------------------- prepare / next
def prepare(a) -> None:
    suite = load_suite(a.suite)
    case = suite["cases"][a.case]
    sdir = SUITES / a.suite
    ver = process_version()
    RUNS.mkdir(parents=True, exist_ok=True)
    migrate_index()
    new = not INDEX.exists()
    with INDEX.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for t in range(1, a.trials + 1):
            rid = secrets.token_hex(3)
            run = RUNS / rid
            ws = run / "workspace"
            (ws / "in").mkdir(parents=True)
            (ws / "out").mkdir()
            for src, dst in case["inputs"].items():
                d = ws / "in" / dst
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(sdir / src, d)
            if a.variant == "skill":
                for base in (".claude/skills", ".github/skills"):
                    shutil.copytree(ROOT / "skills" / case["skill"], ws / base / case["skill"])
            rule = fill(suite["common_output_rule"], version=ver)
            for i, stg in enumerate(case["stages"], 1):
                body = stg["prompt"].rstrip()
                if stg.get("format"):
                    body += "\n\n" + stg["format"].rstrip()
                (run / f"PROMPT_{i}_{stg['id']}.md").write_text(body + "\n\n" + rule, encoding="utf-8")
            (run / "JUDGE.md").write_text(judge_prompt(a.case, case, sdir), encoding="utf-8")
            (run / "human.json").write_text(human_template(a.case, sdir / case["rubric"]), encoding="utf-8")
            save_state(run, {"stage": 0, "approved": []})
            w.writerow({"run_id": rid, "suite": a.suite, "case": a.case, "variant": a.variant, "env": a.env, "trial": t,
                        "process_version": ver, "created": datetime.now().isoformat(timespec="seconds")})
            print(f"[{rid}] {a.suite}/{a.case} {a.env} trial {t}  → python3 eval/kit.py next {rid}")


def next_(a) -> None:
    row, _, case, run = ctx(a.run_id)
    st = state(run)
    stages = case["stages"]
    if st["stage"] >= len(stages):
        print("すべての段階が終わっています。python3 eval/kit.py score", a.run_id)
        return
    i = st["stage"]
    stg = stages[i]
    prompt = run / f"PROMPT_{i + 1}_{stg['id']}.md"
    print(f"段階 {i + 1}/{len(stages)}: {stg['id']}（環境: {row['env']}、新しいセッションで実行する）")
    if row["env"] == "copilot":
        print(f"  1. VS Code で {run / 'workspace'} をフォルダとして開く（ほかのフォルダは開かない）")
        print(f"  2. Copilot Chat を新しく開き、エージェントモードで {prompt} の内容を貼って実行する")
        print(f"  3. 任意: Agent Debug Log からターン数・トークン数を {run / f'agent_output_{i + 1}.json'} に"
              ' {"num_turns": .., "usage": {"output_tokens": ..}} の形で書くと集計に入る')
        print("  スキル無しの場合は、ユーザー設定やほかのワークスペースのスキル・指示ファイルが読まれていないかを、"
              "回答の References 欄で確かめる")
    else:
        print(f"  cd {run / 'workspace'} && claude -p \"$(cat {prompt})\" --output-format json "
              f"--allowedTools Read,Write,Edit,Glob,Grep {NO_PLUGIN} > {run / f'agent_output_{i + 1}.json'}")
    after = "python3 eval/kit.py review " if stg.get("gate") else "python3 eval/kit.py score "
    print("  終わったら:", after + a.run_id)


# ---------------------------------------------------------------- gate
def review(a) -> None:
    row, suite, case, run = ctx(a.run_id)
    st = state(run)
    stg = case["stages"][st["stage"]]
    if not stg.get("gate"):
        print("この段階にはゲートがありません。python3 eval/kit.py score", a.run_id)
        return
    md = run / f"review_{stg['id']}.md"
    md.write_text(f"# ゲート: {stg['id']}（{row['case']}）\n\n", encoding="utf-8")
    run_cmds(stg.get("review"), SUITES / row["suite"], ws=run / "workspace", review=md,
             kit=KIT, suite=SUITES / row["suite"], version=row["process_version"])
    oq = run / "workspace/out/open-questions.md"
    with md.open("a", encoding="utf-8") as f:
        f.write("## 未決事項（生成役が推測せずに残した点）\n\n")
        f.write((oq.read_text(encoding="utf-8") if oq.exists() else "（ファイルなし）") + "\n")
    print(f"{md} を確認してください。承認: python3 eval/kit.py approve {a.run_id}")
    print("差し戻す場合は、同じ段階をもう一度実行してから review してください（python3 eval/kit.py next）")


def approve(a) -> None:
    _, _, case, run = ctx(a.run_id)
    st = state(run)
    stg = case["stages"][st["stage"]]
    if not (run / f"review_{stg['id']}.md").exists():
        sys.exit("先に review を実行し、review の内容を確認してください")
    st["approved"].append({"stage": stg["id"], "at": datetime.now().isoformat(timespec="seconds"), "note": a.note})
    st["stage"] += 1
    save_state(run, st)
    print(f"承認しました（{stg['id']}）。次: python3 eval/kit.py next {a.run_id}")


# ---------------------------------------------------------------- score
def score(a) -> None:
    idx = index()
    for rid in (list(idx) if a.all else a.run_ids):
        row, suite, case, run = ctx(rid)
        st = state(run)
        if st["stage"] < len(case["stages"]) - 1:
            print(f"[{rid}] まだゲートを通っていない段階があります（{case['stages'][st['stage']]['id']}）")
            continue
        st["stage"] = len(case["stages"])
        save_state(run, st)
        ws = run / "workspace"
        hide_skills(rid, ws)
        sdir = SUITES / row["suite"]
        kw = dict(ws=ws, kit=KIT, suite=sdir, version=row["process_version"])
        res = run_cmds(case["checks"], sdir, **kw)
        res["passed"], res["failed_conditions"] = judge_pass(case["pass"], res)
        res["usage"] = [read_usage(p) for p in sorted(run.glob("agent_output_*.json"))]
        (run / "score.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        md = run / "review.md"
        md.write_text(f"# 人の確認（{row['case']}）\n\n生のコードではなく、この表と機械が挙げた点を見て human.json を付けてください。"
                      "judge.json は付け終わってから開いてください。\n\n", encoding="utf-8")
        run_cmds(case.get("review"), sdir, review=md, **kw)
        machine_points(md, res, ws)
        print(f"[{rid}] passed={res['passed']} {res['failed_conditions']}  → {md}")


def machine_points(md: Path, res: dict, ws: Path) -> None:
    lines = ["## 機械が挙げた点", ""]
    lines += [f"- 合格条件を満たしていない: {x}" for x in res["failed_conditions"]]
    if res.get("reference_pass") is False:
        lines.append("- 参照実装でテストが失敗した（契約に無いことを決めつけている可能性）。score.json の reference_log を参照")
    lines += [f"- 見逃したバグ（ミュータント）: {m}" for m in res.get("survived", [])]
    if res.get("result_version_ok") is False:
        lines.append("- result.json に体制の版（process_version）が正しく書かれていない")
    if len(lines) == 2:
        lines.append("- なし")
    oq = ws / "out/open-questions.md"
    lines += ["", "## 未決事項", "", oq.read_text(encoding="utf-8") if oq.exists() else "（ファイルなし）", ""]
    with md.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def hide_skills(rid: str, ws: Path) -> None:
    """採点役と人が、スキル有りか無しかを知らずに採点できるよう、使ったスキルを退避する。"""
    for base in (".claude", ".github"):
        p = ws / base
        if p.exists():
            dst = HIDDEN / rid / base
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dst))


def judge_pass(cond: dict, res: dict) -> tuple[bool, list[str]]:
    failed = []
    for k, want in cond.items():
        key = k[:-4] if k.endswith("_min") else k
        got = res.get(key)
        ok = (got is not None and got >= want) if k.endswith("_min") else got == want
        if not ok:
            failed.append(f"{key}: 期待 {'≥' if k.endswith('_min') else ''}{want} / 実際 {got}")
    return not failed, failed


def read_usage(p: Path) -> dict | None:
    """claude -p --output-format json の出力から数値を拾う（フィールド名は版で変わりうる）。"""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    u = d.get("usage") or {}
    return {"num_turns": d.get("num_turns"), "duration_ms": d.get("duration_ms"), "cost_usd": d.get("total_cost_usd"),
            "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
            "models": sorted((d.get("modelUsage") or {}).keys()) or None}


# ---------------------------------------------------------------- judge / human
def judge_prompt(case_id: str, case: dict, sdir: Path) -> str:
    body = (ROOT / "agents/eval-judge.md").read_text(encoding="utf-8").split("---", 2)[2].strip()
    rubric = (sdir / case["rubric"]).read_text(encoding="utf-8")
    return f"""{body}

## 今回の入力
- case: {case_id}
- inputs_dir: workspace/in
- outputs_dir: workspace/out
- script_result_path: score.json
- human_view_path: review.md（人が見ている表と、機械が挙げた点）

## 採点基準（rubric）
{rubric}
"""


def human_template(case_id: str, rubric: Path) -> str:
    keys = re.findall(r"^\| ([A-Z]-[a-z]+) \|", rubric.read_text(encoding="utf-8"), re.M)
    return json.dumps({"case": case_id, "scores": {k: None for k in keys}, "reasons": {}, "notable": []},
                      ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- summarize
def loose_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    try:
        d = json.loads(text)
        if isinstance(d, dict) and isinstance(d.get("result"), str):   # --output-format json で保存した場合
            text = d["result"]
        else:
            return d
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return round(sum(xs) / len(xs), 2) if xs else None


def fmt(x) -> str:
    return "-" if x is None else str(x)


def summarize(_a) -> None:
    groups: dict[tuple, list[dict]] = {}
    diffs: dict[str, list[int]] = {}
    for r in index().values():
        run = RUNS / r["run_id"]
        s = loose_json(run / "score.json") or {}
        js = (loose_json(run / "judge.json") or {}).get("scores") or {}
        hs = (loose_json(run / "human.json") or {}).get("scores") or {}
        for k in js:
            if isinstance(js.get(k), int) and isinstance(hs.get(k), int):
                diffs.setdefault(k, []).append(abs(js[k] - hs[k]))
        usage = [u for u in s.get("usage") or [] if u]
        groups.setdefault((r["suite"], r["case"], r["variant"], r["env"], r["process_version"]), []).append({
            "passed": s.get("passed"), "kill_rate": s.get("kill_rate"),
            "judge": mean(list(js.values())), "human": mean(list(hs.values())),
            "out_tokens": sum(u.get("output_tokens") or 0 for u in usage) or None,
            "turns": sum(u.get("num_turns") or 0 for u in usage) or None})
    lines = ["# 集計", "",
             "| 題材 | ケース | スキル | 環境 | 体制の版 | 回数 | スクリプト合格 | 検出率 | LLM採点 | 人の採点 | 出力トークン | ターン |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (suite, case, variant, env, ver), items in sorted(groups.items()):
        scored = [i for i in items if i["passed"] is not None]
        rate = f"{sum(i['passed'] for i in scored)}/{len(scored)}" if scored else "-"
        cols = [mean([i[k] for i in items]) for k in ("kill_rate", "judge", "human", "out_tokens", "turns")]
        lines.append(f"| {suite} | {case} | {variant} | {env} | {ver} | {len(items)} | {rate} | " + " | ".join(map(fmt, cols)) + " |")
    lines += ["", "## LLM採点と人の採点のずれ（観点別、差の絶対値の平均。1未満が目安）", "",
              "| 観点 | 件数 | 平均の差 | 差が2以上 |", "|---|---|---|---|"]
    lines += [f"| {k} | {len(d)} | {mean(d)} | {sum(x >= 2 for x in d)} |" for k, d in sorted(diffs.items())] or \
             ["| （人の採点がまだ無い） | | | |"]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("prepare"); p.add_argument("case"); p.add_argument("--suite", required=True)
    p.add_argument("--variant", choices=["noskill", "skill"], required=True); p.add_argument("--trials", type=int, default=3)
    p.add_argument("--env", choices=ENVS, default="claude", help="生成役を動かす環境（D19）")
    p.set_defaults(fn=prepare)
    for name, fn in (("next", next_), ("review", review)):
        s = sub.add_parser(name); s.add_argument("run_id"); s.set_defaults(fn=fn)
    s = sub.add_parser("approve"); s.add_argument("run_id"); s.add_argument("--note", default=""); s.set_defaults(fn=approve)
    s = sub.add_parser("score"); s.add_argument("run_ids", nargs="*"); s.add_argument("--all", action="store_true"); s.set_defaults(fn=score)
    s = sub.add_parser("summarize"); s.set_defaults(fn=summarize)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
