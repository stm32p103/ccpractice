"""処理系の設定 (toolchains/*.json) に従って sample.c をビルドし, 左辺値の解決結果を
コンパイラ自身が計算した正解と比べて result.md を出力する。

usage:
    dsr-verify-toolchain verification/toolchains/arm_gcc.json [variant ...] [--build-only] [--debug-info MOD:CLASS]
    (または python -m dwarf_symbol_resolver.devtools.verify_toolchain ...)

    --build-only : プリプロセス・コンパイル・リンクができるかだけ確認する (解析はしない)
    --debug-info : 設定の debug_info の代わりに使う DebugInfoSource
                   (例 dwarf_symbol_resolver.sources.dwarf.common:DwarfSource)
    --workdir    : sample.c と lvalues.txt のあるディレクトリ (既定: 設定ファイルのディレクトリの親)

設定ファイル (JSON):
    name        : 処理系の名前
    out_dir     : 出力先 (workdir からの相対, {name} {variant} を置換。既定 "results/{name}/{variant}")
    variants    : {バリアント名: [追加オプション]}  (例 DWARF のバージョン違い)
    preprocess  : プリプロセスのコマンド (引数の配列)。{src} {out} を置換
    compile     : コンパイルのコマンド。{src} {obj} を置換, "{variant_flags}" はバリアントのオプション列に展開
    link        : リンクのコマンド。{obj} {elf} を置換
    debug_info  : DebugInfoSource のクラス ("モジュール:クラス")
    local_static_pattern : 関数内 static のシンボル名の正規表現 ({name} が変数名)
    typeof      : 検証コードで使う typeof のキーワード (既定 "__typeof__")
    remarks     : result.md の「考察」に載せる文 {"*": [...], "<variant>": [...]}

出力 (out_dir):
    sample.i, probe.c/.i, sample.o, app.elf, verify.c/.o/.elf, result.md
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys

from dwarf_symbol_resolver import ElfSymtabSource, Linkage, ResolveError, SymbolResolver
from dwarf_symbol_resolver.devtools.survey import survey
from dwarf_symbol_resolver.examples.monitor_info import MONITOR_PARSERS, MonitorInfo  # 利用者側の T と build の例

HERE = ""      # workdir (main で設定)
SAMPLE_C = ""  # workdir/sample.c (#include 用にスラッシュ区切り)


def set_workdir(path):
    global HERE, SAMPLE_C
    HERE = os.path.abspath(path)
    SAMPLE_C = os.path.join(HERE, "sample.c").replace("\\", "/")


# ---------------------------------------------------------------- 設定・コマンド

def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("out_dir", "results/{name}/{variant}")
    cfg.setdefault("variants", {"default": []})
    cfg.setdefault("debug_info", "dwarf_symbol_resolver.sources.dwarf.common:DwarfSource")
    cfg.setdefault("local_static_pattern", r"{name}\.\d+")
    cfg.setdefault("typeof", "__typeof__")
    cfg.setdefault("remarks", {})
    return cfg


def expand(template, variant_flags=(), **kw):
    out = []
    for a in template:
        if a == "{variant_flags}":
            out += list(variant_flags)
        else:
            out.append(a.format(**kw))
    return out


def sh(args, cwd):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"コマンド失敗 (exit {r.returncode}): {' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout + r.stderr


def load_class(spec):
    mod, cls = spec.split(":")
    return getattr(importlib.import_module(mod), cls)


# ---------------------------------------------------------------- ビルド

def build(cfg, flags, out, src=None, stem="sample", elf="app.elf"):
    """src (既定 sample.c) をプリプロセス・コンパイル・リンクする。出力したコマンドの一覧を返す"""
    src = src or SAMPLE_C
    cmds = []
    if stem == "sample":
        cmds.append(expand(cfg["preprocess"], src=src, out="sample.i"))
    cmds.append(expand(cfg["compile"], flags, src=src, obj=f"{stem}.o"))
    cmds.append(expand(cfg["link"], obj=f"{stem}.o", elf=elf))
    for c in cmds:
        sh(c, out)
    return cmds


def load_lvalues():
    out = []
    with open(os.path.join(HERE, "lvalues.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append((line.lstrip("!"), line.startswith("!")))
    return out


def split_scope(lhs):
    if "::" in lhs:
        *scope, expr = lhs.split("::")
        return "::".join(scope) + "::", expr
    return "", lhs


def probe_expand(cfg, lvs, out):
    """処理系のプリプロセッサでマクロを展開する"""
    lines = [f'#include "{SAMPLE_C}"']
    for i, (lhs, _) in enumerate(lvs):
        lines.append(f"__LV_BEGIN_{i}__ {split_scope(lhs)[1]} __LV_END__")
    with open(os.path.join(out, "probe.c"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sh(expand(cfg["preprocess"], src="probe.c", out="probe.i"), out)
    with open(os.path.join(out, "probe.i"), encoding="utf-8", errors="replace") as f:
        text = f.read()
    return {int(m.group(1)): " ".join(m.group(2).split())
            for m in re.finditer(r"__LV_BEGIN_(\d+)__(.*?)__LV_END__", text, re.S)}


# ---------------------------------------------------------------- 検証

def build_verify(cfg, flags, out, items):
    """コンパイラに正解を出させる TU (sample.c を include するので static も参照できる)"""
    lines = [f'#include "{SAMPLE_C}"', ""]
    for i, it in enumerate(items):
        r = it.get("res")
        if r is None or r.linkage is Linkage.LOCAL_STATIC:
            continue
        lines.append(f"/* {it['lhs']} */")
        if r.mask is None:
            lines.append(f"const volatile void *const lv_addr_{i} = (const volatile void *)&({it['expanded']});")
            lines.append(f"const unsigned int lv_size_{i} = sizeof({it['expanded']});")
        else:  # ルート型のゼロ初期化オブジェクトで, 対象フィールドだけを全ビット1にする
            lines.append(f"__attribute__((used)) static const {cfg['typeof']}({r.path.root}) lv_img_{i} = "
                         f"{{ {r.path.designator()} = -1 }};")
    with open(os.path.join(out, "verify.c"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    build(cfg, flags, out, src="verify.c", stem="verify", elf="verify.elf")


def read_sym(elf, name):
    for s in elf.get_section_by_name(".symtab").iter_symbols():
        if s.name == name:
            addr, size = s["st_value"], s["st_size"]
            for sec in elf.iter_sections():
                a = sec["sh_addr"]
                if sec["sh_type"] != "SHT_NOBITS" and a <= addr < a + sec["sh_size"]:
                    return sec.data()[addr - a: addr - a + size]
    return None


def check(cfg, debug_cls, items, out):
    """verify.elf を同じ DebugInfoSource で解決し, コンパイラの正解と比較"""
    from elftools.elf.elffile import ELFFile
    path = os.path.join(out, "verify.elf")
    vr = SymbolResolver(debug_cls(path), [ElfSymtabSource(path, cfg["local_static_pattern"])])
    symtab = ElfSymtabSource(os.path.join(out, "app.elf"), cfg["local_static_pattern"])
    with open(path, "rb") as f:
        elf = ELFFile(f)
        for i, it in enumerate(items):
            r = it.get("res")
            if r is None:
                continue
            if r.linkage is Linkage.LOCAL_STATIC:
                hits = symtab.candidates(r.variable)
                ok = len(hits) == 1 and hits[0]["addr"] == r.root_address
                it["check"] = (f"△ シンボル表 `{hits[0]['name']}` と一致" if ok else
                               f"✗ シンボル表と不一致 ({[h['name'] for h in hits]})")
                continue
            p = it["path"]  # verify.elf では翻訳単位名が verify.c
            p = type(p)(p.root, tuple("verify.c" if s.endswith(".c") else s for s in p.scope), p.steps)
            try:
                v = vr.resolve(p)
            except ResolveError as e:
                it["check"] = f"✗ verify側で失敗: {e}"
                continue
            if r.mask is None:
                ta = int.from_bytes(read_sym(elf, f"lv_addr_{i}"), "little")
                ts = int.from_bytes(read_sym(elf, f"lv_size_{i}"), "little")
                ok = ta == v.address and ts == v.size
                it["check"] = "✓" if ok else f"✗ 正解 addr=0x{ta:X} size={ts} / 推定 0x{v.address:X} {v.size}"
            else:
                img = read_sym(elf, f"lv_img_{i}")
                expect = bytearray(len(img))
                expect[v.root_offset:v.root_offset + v.size] = v.mask.to_bytes(v.size, "little")
                it["check"] = "✓" if bytes(expect) == bytes(img) else \
                    f"✗ 正解 {img.hex()} / 推定 {bytes(expect).hex()}"
    vr.close()


# ---------------------------------------------------------------- 出力

def fmt_comment(c: MonitorInfo | None):
    if c is None:
        return "-"
    parts = []
    if c.unit:
        parts.append(f"単位={c.unit}")
    if c.lsb_expr:
        parts.append(f"LSB={c.lsb_expr}" + (f"(={float(c.lsb):.6g})" if c.lsb is not None else "(評価失敗)"))
    if c.offset_expr:
        parts.append(f"OFS={c.offset_expr}")
    if c.description:
        parts.append(c.description)
    return f"[{c.style}] " + ", ".join(parts)


def report(cfg, variant, cmds, debug_cls, res, items, out):
    def cnt(pred):
        return sum(1 for it in items if pred(it))
    normal = cnt(lambda it: not it["expect_err"])
    ok = cnt(lambda it: not it["expect_err"] and it.get("check", "").startswith("✓"))
    tri = cnt(lambda it: not it["expect_err"] and it.get("check", "").startswith("△"))
    errs = cnt(lambda it: it["expect_err"])
    err_ok = cnt(lambda it: it["expect_err"] and "err" in it and "res" not in it)

    L = [f"# {cfg['name']} / {variant} 検証結果", "",
         f"- デバッグ情報: {res.debug_info.describe()} (`{debug_cls.__module__}.{debug_cls.__name__}`)",
         "- プリプロセス: `" + " ".join(cmds[0]) + "`",
         "- コンパイル: `" + " ".join(cmds[1]) + "`",
         "- リンク: `" + " ".join(cmds[2]) + "`",
         "- マクロ展開: `probe.c` (`#include` で sample.c を取り込み, 目印付きの左辺値を並べたもの) をプリプロセス → `probe.i`",
         "- 正解: `verify.c` を同じオプションでビルドし, コンパイラが計算した `&(lhs)` / `sizeof(lhs)` / "
         "ビットフィールドだけ全ビット1にした初期化イメージを, リゾルバの推定と比較", "",
         "## まとめ", "",
         f"- 正常系 {normal} 件: コンパイラの正解と一致 {ok} 件, シンボル表との照合のみ {tri} 件, "
         f"その他 {normal - ok - tri} 件",
         f"- エラー期待 {errs} 件: 正しくエラー {err_ok} 件", ""]
    remarks = cfg["remarks"].get("*", []) + cfg["remarks"].get(variant, [])
    if remarks:
        L += ["## 考察", ""] + [f"- {r}" for r in remarks] + [""]
    L += ["## ELF / DWARF の観察 (dwarf_survey)", ""] + survey(os.path.join(out, "app.elf"))
    L += ["## 左辺値ごとの結果", "",
          "| 左辺値 | 展開後 | アドレス | 幅 | マスク | 型 | 解釈 | 結合 | コメント | 検証 | 備考 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for it in items:
        lhs, e = it["lhs"].replace("|", "\\|"), it["expanded"].replace("|", "\\|")
        if "res" in it:
            r = it["res"]
            mask = f"0x{r.mask:0{r.size * 2}X}" if r.mask is not None else "-"
            L.append(f"| `{lhs}` | `{e}` | 0x{r.address:08X} | {r.size * 8}bit | {mask} | {r.ctype} | "
                     f"{r.encoding.value if r.encoding else '-'} | {r.linkage.value} | "
                     f"{fmt_comment(r.comment)} | {it.get('check', '-')} | {'; '.join(r.notes)} |")
        else:
            mark = "✓ (期待どおりエラー)" if it["expect_err"] else "✗"
            L.append(f"| `{lhs}` | `{e}` | - | - | - | - | - | - | - | {mark} | {it['err']} |")
    with open(os.path.join(out, "result.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return ok, tri, normal, err_ok, errs


# ---------------------------------------------------------------- メイン

def run_variant(cfg, variant, build_only=False, debug_spec=None):
    flags = cfg["variants"][variant]
    out = os.path.join(HERE, cfg["out_dir"].format(name=cfg["name"], variant=variant))
    os.makedirs(out, exist_ok=True)
    cmds = build(cfg, flags, out)
    if build_only:
        print(f"[{variant}] ビルド成功: {os.path.relpath(out, HERE)}/app.elf")
        for c in cmds:
            print("   ", " ".join(c))
        return True
    debug_cls = load_class(debug_spec or cfg["debug_info"])
    lvs = load_lvalues()
    exp = probe_expand(cfg, lvs, out)
    elf = os.path.join(out, "app.elf")
    addr = [ElfSymtabSource(elf, cfg["local_static_pattern"])]
    res = SymbolResolver(debug_cls(elf), addr, [HERE], MONITOR_PARSERS)
    items = []
    for i, (lhs, expect_err) in enumerate(lvs):
        scope, _ = split_scope(lhs)
        it = {"lhs": lhs, "expect_err": expect_err, "expanded": exp.get(i, "?")}
        try:
            it["path"] = res.parse(scope + it["expanded"])
            it["res"] = res.resolve(it["path"])
        except ResolveError as e:
            it["err"] = str(e)
        items.append(it)
    build_verify(cfg, flags, out, items)
    check(cfg, debug_cls, items, out)
    ok, tri, normal, err_ok, errs = report(cfg, variant, cmds, debug_cls, res, items, out)
    res.close()
    print(f"[{variant}] 正常系 一致 {ok} + 照合のみ {tri} / {normal}, エラー期待 {err_ok}/{errs} "
          f"→ {os.path.relpath(out, HERE)}/result.md")
    return ok + tri == normal and err_ok == errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("variants", nargs="*")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--debug-info")
    ap.add_argument("--workdir")
    a = ap.parse_args()
    cfg = load_config(a.config)
    set_workdir(a.workdir or os.path.dirname(os.path.dirname(os.path.abspath(a.config))))
    all_ok = True
    for v in a.variants or list(cfg["variants"]):
        try:
            all_ok &= run_variant(cfg, v, a.build_only, a.debug_info)
        except RuntimeError as e:
            print(f"[{v}] {e}")
            all_ok = False
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
