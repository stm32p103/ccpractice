"""語彙検査(004 SC-008、US5-2)。runner-agent・runner-protocol のソースに、用途固有の語・プラットフォームの語がない。"""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE_TERMS = ROOT / "core" / "tests" / "architecture" / "forbidden_terms.txt"
RUNNER_TERMS = HERE / "forbidden_terms_runner.txt"
SOURCE_ROOTS = [
    ROOT / "runner-agent" / "src" / "job_runner_agent",
    ROOT / "runner-protocol" / "src" / "job_runner_protocol",
]


def terms() -> list[str]:
    out: list[str] = []
    for file in (CORE_TERMS, RUNNER_TERMS):
        for line in file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line.lower())
    return out


def scanned() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        files += [p for p in root.rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".txt", ".md"}]
    return sorted(files)


def test_terms_are_loaded() -> None:
    assert len(terms()) >= 5


@pytest.mark.parametrize("path", scanned(), ids=lambda p: p.name)
def test_no_forbidden_terms(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()
    found = [t for t in terms() if t in text]
    assert found == [], f"{path} に禁止語: {found}"
