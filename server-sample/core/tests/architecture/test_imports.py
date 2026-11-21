"""標準ライブラリのみ・禁止 API の検査(FR-028、FR-029。research.md R15-2、R15-3)。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "job_core"

# 外部への送信・外部プロセスの実行に当たる標準モジュール(FR-029)
FORBIDDEN_STDLIB = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "socketserver",
    "subprocess",
    "multiprocessing",
    "asyncio",
    "webbrowser",
    "ctypes",
}


def source_files() -> list[Path]:
    files = sorted(SOURCE_ROOT.rglob("*.py"))
    assert files, f"{SOURCE_ROOT} にソースがない"
    return files


def imported_top_level_modules(path: Path) -> set[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add((node.module.split(".")[0], node.lineno))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
            found.add(("__import__", node.lineno))
    return found


@pytest.mark.parametrize("path", source_files(), ids=lambda p: str(p.relative_to(SOURCE_ROOT)))
def test_only_stdlib_and_job_core(path: Path) -> None:
    violations = [
        f"{name} (行 {line})"
        for name, line in imported_top_level_modules(path)
        if name not in sys.stdlib_module_names and name != "job_core" and name != "__future__"
    ]
    assert violations == []


@pytest.mark.parametrize("path", source_files(), ids=lambda p: str(p.relative_to(SOURCE_ROOT)))
def test_no_forbidden_stdlib_or_dynamic_import(path: Path) -> None:
    violations = [
        f"{name} (行 {line})"
        for name, line in imported_top_level_modules(path)
        if name in FORBIDDEN_STDLIB or name in {"__import__", "importlib"}
    ]
    assert violations == []


def test_detector_finds_violations(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import socket\nfrom urllib import request\nimport requests\n", encoding="utf-8")
    names = {name for name, _ in imported_top_level_modules(sample)}
    assert {"socket", "urllib", "requests"} <= names
