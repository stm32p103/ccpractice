"""語彙検査(SC-009。research.md R15-4)。

job_core のソース(識別子・文字列・コメント)に、forbidden_terms.txt の語が含まれないことを確認する。
禁止語の一覧は、検査対象のソースの外(このディレクトリのテキストファイル)だけに置く。
"""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parents[1] / "src" / "job_core"
TERMS_FILE = HERE / "forbidden_terms.txt"


def forbidden_terms() -> list[str]:
    lines = TERMS_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip().lower() for line in lines if line.strip() and not line.strip().startswith("#")]


def scanned_files() -> list[Path]:
    return sorted(p for p in SOURCE_ROOT.rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".txt", ".md"})


def find_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def test_terms_file_is_not_empty() -> None:
    assert len(forbidden_terms()) >= 5


@pytest.mark.parametrize("path", scanned_files(), ids=lambda p: str(p.relative_to(SOURCE_ROOT)))
def test_no_forbidden_terms(path: Path) -> None:
    found = find_terms(path.read_text(encoding="utf-8"), forbidden_terms())
    assert found == [], f"{path} に禁止語: {found}"


def test_detector_is_case_insensitive() -> None:
    assert find_terms("# uses GitHub here", ["github"]) == ["github"]
