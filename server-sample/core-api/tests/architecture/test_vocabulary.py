"""語彙検査(SC-009。research.md R15)。

core-api のソース(識別子・文字列・コメント)と OpenAPI の文書に、forbidden_terms.txt の語(プラットフォーム・
用途固有の語)が含まれないこと。禁止語の一覧は core の一覧を共有する(語を増やさない)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_testing.vocabulary import find_terms, forbidden_terms

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "job_core_api"
OPENAPI = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.json"


def scanned_files() -> list[Path]:
    return sorted(p for p in SOURCE_ROOT.rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".txt", ".md"})


def test_terms_are_shared_with_core_and_not_empty() -> None:
    assert len(forbidden_terms()) >= 5


@pytest.mark.parametrize("path", scanned_files(), ids=lambda p: str(p.relative_to(SOURCE_ROOT)))
def test_no_forbidden_terms_in_source(path: Path) -> None:
    found = find_terms(path.read_text(encoding="utf-8"), forbidden_terms())
    assert found == [], f"{path} に禁止語: {found}"


def test_no_forbidden_terms_in_the_openapi_document() -> None:
    text = json.dumps(json.loads(OPENAPI.read_text(encoding="utf-8")), ensure_ascii=False)
    assert find_terms(text, forbidden_terms()) == []
