"""利用例: 左辺値の一覧から RAM モニタツール用の設定 (CSV) を作るツール。

ツール開発者がこのライブラリをどう組み込むかの見本。流れは次のとおり。

    1. 左辺値の一覧 (マクロを含んでよい) を読む
    2. ビルドと同じプリプロセッサでマクロを展開する (ライブラリはマクロ展開をしない)
    3. SymbolResolver で解決する (コメントは examples.monitor_info の MonitorInfo として受け取る)
    4. Resolved を自ツールの形式 (ここでは CSV) に変換する。値の加工はツール側の責任

usage:
    python -m dwarf_symbol_resolver.examples.export_monitor_csv \\
        --elf verification/results/arm_gcc/v4/app.elf \\
        --context verification/sample.c --src-dir verification \\
        --cpp "arm-none-eabi-gcc -E -P {src} -o {out}" \\
        --lvalues verification/lvalues.txt -o monitor.csv

    --context : マクロを展開する文脈の翻訳単位 (この .c を #include してから左辺値を展開する)
    --cpp     : プリプロセスのコマンド ({src} {out} を置換)。ビルドと同じ -D / -I を付けること
    --lvalues : 1 行 1 左辺値。"#" 始まりはコメント, "!" 始まり (エラー期待) は読み飛ばす。
                関数内 static は "関数名::変数名", ファイル内 static は "ファイル名::変数名"
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shlex
import subprocess
import sys
import tempfile

from dwarf_symbol_resolver import ArmGccDwarfSource, ElfSymtabSource, ResolveError, SymbolResolver
from dwarf_symbol_resolver.examples.monitor_info import MONITOR_PARSERS, MonitorInfo


def expand_macros(exprs: list[str], context_c: str, cpp: str) -> list[str]:
    """プリプロセッサでマクロを展開する。exprs の各要素の展開結果を同じ順で返す"""
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, "probe.c"), os.path.join(d, "probe.i")
        with open(src, "w", encoding="utf-8") as f:
            f.write(f'#include "{os.path.abspath(context_c).replace(os.sep, "/")}"\n')
            for i, e in enumerate(exprs):
                f.write(f"__LV_BEGIN_{i}__ {e} __LV_END__\n")
        cmd = [a.format(src=src, out=out) for a in shlex.split(cpp)]
        subprocess.run(cmd, check=True, capture_output=True)
        text = open(out, encoding="utf-8", errors="replace").read()
    found = {int(m.group(1)): " ".join(m.group(2).split())
             for m in re.finditer(r"__LV_BEGIN_(\d+)__(.*?)__LV_END__", text, re.S)}
    return [found.get(i, e) for i, e in enumerate(exprs)]


def split_scope(lhs: str) -> tuple[str, str]:
    """"tick::call_cnt" → ("tick::", "call_cnt")。スコープはマクロ展開の対象外"""
    if "::" in lhs:
        scope, expr = lhs.rsplit("::", 1)
        return scope + "::", expr
    return "", lhs


def to_row(name: str, expanded: str, r, info: MonitorInfo | None) -> dict:
    """Resolved → CSV の 1 行 (ツール固有の変換)"""
    return {
        "name": name,
        "expr": expanded,
        "address": f"0x{r.address:08X}",
        "bytes": r.size,
        "mask": f"0x{r.mask:X}" if r.mask is not None else "",
        "shift": r.shift if r.shift is not None else "",
        "bits": r.bit_size or r.size * 8,
        "type": r.encoding.value if r.encoding else "",
        "unit": info.unit if info else "",
        "lsb": float(info.lsb) if info and info.lsb is not None else "",
        "offset": float(info.offset) if info and info.offset is not None else "",
        "description": info.description if info else "",
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", required=True)
    ap.add_argument("--context", required=True)
    ap.add_argument("--src-dir", action="append", default=[])
    ap.add_argument("--cpp", required=True)
    ap.add_argument("--lvalues", required=True)
    ap.add_argument("-o", "--output", default="-")
    a = ap.parse_args(argv)

    with open(a.lvalues, encoding="utf-8") as f:
        names = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith(("#", "!"))]
    scopes, exprs = zip(*(split_scope(n) for n in names)) if names else ((), ())
    expanded = expand_macros(list(exprs), a.context, a.cpp)

    resolver = SymbolResolver(ArmGccDwarfSource(a.elf),           # 処理系に合ったクラスを選ぶ
                              [ElfSymtabSource(a.elf)],
                              src_dirs=a.src_dir or [os.path.dirname(a.context)],
                              comment_parsers=MONITOR_PARSERS)
    rows, errors = [], []
    for name, scope, exp in zip(names, scopes, expanded):
        try:
            r = resolver.resolve(scope + exp)
        except ResolveError as e:
            errors.append(f"{name}: {e}")
            continue
        rows.append(to_row(name, exp, r, r.comment))
    resolver.close()

    out = sys.stdout if a.output == "-" else open(a.output, "w", newline="", encoding="utf-8")
    w = csv.DictWriter(out, fieldnames=list(rows[0]) if rows else ["name"])
    w.writeheader()
    w.writerows(rows)
    if out is not sys.stdout:
        out.close()
    for e in errors:
        print(f"解決できない: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
