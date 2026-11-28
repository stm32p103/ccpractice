"""コメント形式を集約し, 自己テストと衝突確認を行う。

usage (リポジトリのルートで実行):
    python src/dwarf_symbol_resolver/devtools/comment_catalog.py           # 検査だけ (結果を表示)
    python src/dwarf_symbol_resolver/devtools/comment_catalog.py --write   # 検査 + 一覧を再生成

    dsr-comment-catalog [--write] でも実行できる。ただし形式のモジュールを削除・改名した直後は,
    古い formats/__init__.py のせいでパッケージの import に失敗するので, 上のファイル指定の形で実行する
    (ファイル指定なら, パッケージを import する前に一覧を空にできる)

出力:
    src/dwarf_symbol_resolver/comments/formats/__init__.py  … 形式の import と ALL_FORMATS
    src/dwarf_symbol_resolver/comments/CATALOG.md           … 形式ごとの正規表現・サンプル・衝突の一覧
終了コード: 問題 (自己テスト失敗・衝突) があれば 1
"""
import argparse
import os
import sys

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/dwarf_symbol_resolver
FORMATS_INIT = os.path.join(PKG_DIR, "comments", "formats", "__init__.py")
STUB = '"""コメント形式の一覧 (再生成中)"""\nALL_FORMATS = []\n__all__ = ["ALL_FORMATS"]\n'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)

    if a.write:
        # 削除・改名されたモジュールを import して失敗しないよう, 先に一覧を空にしてから集め直す
        with open(FORMATS_INIT, "w", encoding="utf-8") as fp:
            fp.write(STUB)
    from dwarf_symbol_resolver.comments import catalog
    formats = catalog.discover()
    for f in formats:
        f.problems = catalog.self_test(f)
    cols = catalog.collisions(formats)

    for f in formats:
        print(f"{'OK ' if not f.problems else 'NG '} {f.name} (formats/{f.module}.py, parsed={f.parsed_type}, "
              f"samples={len(f.cls.samples)})")
        for p in f.problems:
            print(f"     - {p}")
    print(f"衝突: {len(cols)} 件")
    for c in cols:
        print(f"     - {c.pattern_owner} の pattern が {c.sample_owner} のサンプル {c.comment!r} に合致")

    if a.write:
        catalog.write_init(formats)
        path = os.path.join(os.path.dirname(catalog.__file__), "CATALOG.md")
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(catalog.catalog_markdown(formats, cols))
        print(f"生成: {os.path.relpath(catalog.FORMATS_DIR, os.getcwd())}/__init__.py, "
              f"{os.path.relpath(path, os.getcwd())}")
    sys.exit(1 if cols or any(f.problems for f in formats) else 0)


if __name__ == "__main__":
    if __package__ in (None, ""):  # ファイル指定で実行: src をパスに加える
        sys.path.insert(0, os.path.dirname(PKG_DIR))
    main()
