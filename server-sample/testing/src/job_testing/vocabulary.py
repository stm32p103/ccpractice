"""語彙検査の補助(禁止語の一覧は core の一覧を共有する。語を増やさない)。"""

from __future__ import annotations

from pathlib import Path

TERMS_FILE = Path(__file__).resolve().parents[3] / "core" / "tests" / "architecture" / "forbidden_terms.txt"


def forbidden_terms() -> list[str]:
    lines = TERMS_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip().lower() for line in lines if line.strip() and not line.strip().startswith("#")]


def find_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]
