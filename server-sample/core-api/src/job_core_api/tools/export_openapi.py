"""OpenAPI のスナップショットの書き出し(research.md R3)。

`uv run python -m job_core_api.tools.export_openapi` で `core-api/openapi/openapi-v1.json` を更新する。
`--check` は、書き出さずに、現在の実装から生成した文書とスナップショットの一致だけを確かめる(CI・検査用)。
意図した変更なら、更新したファイルをコミットする。破壊的変更は、直前の公開版 `core-api/openapi/released/` との
比較(`openapi_compat`)で検出される。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..app import openapi_document

SNAPSHOT = Path(__file__).resolve().parents[3] / "openapi" / "openapi-v1.json"
RELEASED_DIR = SNAPSHOT.parent / "released"


def render(document: dict[str, Any]) -> str:
    """安定した形(キーを整列、UTF-8、末尾に改行)で JSON にする。"""
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    text = render(openapi_document())
    if "--check" in args:
        current = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.exists() else ""
        if current != text:
            print("OpenAPI のスナップショットと実装が一致しない。更新: python -m job_core_api.tools.export_openapi")
            return 1
        return 0
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(text, encoding="utf-8", newline="\n")
    print(f"書き出した: {SNAPSHOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
