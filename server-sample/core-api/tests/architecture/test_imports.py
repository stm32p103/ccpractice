"""依存規則の検査(憲章 原則 3。research.md R1)。`lint-imports` を呼び、契約違反が 0 件であることを確かめる。

契約(.importlinter): job_core_api は永続化・組み立て・テスト部品を import しない、job_core_persistence は
job_core_server を import しない、job_core は API・永続化・組み立てを import しない。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_import_linter_contracts_are_kept() -> None:
    executable = Path(sys.executable).parent / ("lint-imports.exe" if sys.platform == "win32" else "lint-imports")
    result = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout


def test_the_three_new_contracts_exist() -> None:
    text = (ROOT / ".importlinter").read_text(encoding="utf-8")
    for contract in ("api-independent-of-impl", "persistence-independent-of-server", "core-independent-of-api"):
        assert f"importlinter:contract:{contract}" in text
