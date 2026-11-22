"""禁止 API の検査(FR-023、憲章 S2。research.md R12)。

`job_core_api`・`job_core_persistence` に、外向きの通信に当たる API(`httpx`・`requests`・`urllib.request`・
`http.client`・`aiohttp`・`socket` など)の直接の利用がない。通信するアダプタは、台帳に出力先を追加して
レビューを受けた実装だけに置く(005)。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = [ROOT / "core-api" / "src" / "job_core_api", ROOT / "core-persistence" / "src" / "job_core_persistence"]

FORBIDDEN_MODULES = {
    "httpx",
    "httpx2",
    "requests",
    "aiohttp",
    "urllib3",
    "socket",
    "ssl",
    "http.client",
    "urllib.request",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "websockets",
    "websocket",
}


def sources() -> list[Path]:
    return sorted(p for package in PACKAGES for p in package.rglob("*.py"))


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


@pytest.mark.parametrize("path", sources(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_outbound_communication_api_is_used(path: Path) -> None:
    violations = sorted(
        name
        for name in imported_modules(path)
        if name in FORBIDDEN_MODULES or any(name.startswith(prefix + ".") for prefix in FORBIDDEN_MODULES)
    )
    assert violations == [], f"{path} が外向きの通信の API を使っている: {violations}"


def test_the_detector_finds_violations(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import httpx\nfrom urllib import request\nfrom http.client import HTTPConnection\n", "utf-8")
    names = imported_modules(sample)
    assert {"httpx", "urllib.request", "http.client"} <= names
    assert names & FORBIDDEN_MODULES >= {"httpx", "urllib.request", "http.client"}


def test_no_dynamic_import_tricks_in_the_api_package() -> None:
    for path in sources():
        text = path.read_text(encoding="utf-8")
        assert "__import__(" not in text, path
