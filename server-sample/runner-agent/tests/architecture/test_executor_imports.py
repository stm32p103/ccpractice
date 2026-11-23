"""エグゼキュータにプロセスを起動させない(T065)、エージェントの外向きの通信・プロセス起動の場所の限定(T085。S2、S4)。

AST で import と呼び出しを検査する。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / "runner-agent" / "src" / "job_runner_agent"
PROFILE = ROOT / "profile-equipment-check" / "src" / "job_profile_equipment_check"
PROTOCOL = ROOT / "runner-protocol" / "src" / "job_runner_protocol"
SERVICE = ROOT / "runner-service" / "src" / "job_runner_service"

EXECUTOR_FORBIDDEN = {
    "subprocess",
    "os",
    "socket",
    "http",
    "urllib",
    "ctypes",
    "asyncio",
    "httpx",
    "requests",
    "shutil",
    "multiprocessing",
}
PROCESS_MODULES = {"subprocess", "multiprocessing"}
NETWORK_MODULES = {
    "socket",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "ssl",
    "httpx",
    "requests",
    "aiohttp",
    "xmlrpc",
    "telnetlib",
}
TELEMETRY_MODULES = {"opentelemetry", "sentry_sdk", "posthog", "mixpanel", "analytics"}
OS_COMMAND_CALLS = {"system", "popen", "startfile", "spawnl", "spawnv", "execv", "execl"}


def imports_of(path: Path) -> set[str]:
    """import しているモジュールの最上位の名前。`urllib.parse`(文字列の符号化。通信ではない)は含めない。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            if name == "urllib.parse":
                continue
            found.add(name.split(".")[0])
    return found


def files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


@pytest.mark.parametrize("path", files(PROFILE), ids=lambda p: p.name)
def test_executors_do_not_launch_processes_or_use_network(path: Path) -> None:
    bad = imports_of(path) & EXECUTOR_FORBIDDEN
    assert bad == set(), f"{path.name}: エグゼキュータが {bad} を import している"


@pytest.mark.parametrize("path", files(AGENT), ids=lambda p: str(p.relative_to(AGENT)))
def test_subprocess_is_used_only_by_the_launcher(path: Path) -> None:
    relative = path.relative_to(AGENT)
    if relative.parts[0] == "launcher":
        return
    assert imports_of(path) & PROCESS_MODULES == set(), f"{relative}: プロセスの起動は launcher/ だけ"


ALLOWED_NETWORK = {"core_client.py"}  # コア API へのクライアント(httpx)。台帳 E4〜E7・E16 の宛先は設定の 1 か所


@pytest.mark.parametrize("path", files(AGENT) + files(PROTOCOL), ids=lambda p: p.name)
def test_network_libraries_are_confined_to_the_core_client(path: Path) -> None:
    bad = imports_of(path) & NETWORK_MODULES
    if path.name in ALLOWED_NETWORK:
        assert bad <= {"httpx"}
    else:
        assert bad == set(), f"{path.name}: 通信の部品は core_client.py だけ"


@pytest.mark.parametrize("path", files(AGENT) + files(PROTOCOL) + files(PROFILE) + files(SERVICE), ids=lambda p: p.name)
def test_no_telemetry_and_no_os_command_calls(path: Path) -> None:
    assert imports_of(path) & TELEMETRY_MODULES == set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in OS_COMMAND_CALLS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            raise AssertionError(f"{path.name}: os.{node.func.attr} を呼ばない(シェルを介さない)")
    source = path.read_text(encoding="utf-8")
    assert "shell=True" not in source


def test_agent_has_no_git_client() -> None:
    """エージェントは Git にコミット・プッシュしない(FR-019)。Git のクライアント・コマンドを持たない。"""
    for path in files(AGENT):
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in ("git push", "git commit", '"git"', "'git'", "gitpython", "dulwich", "pygit2"):
            assert forbidden not in text, f"{path.name}: {forbidden}"


def test_service_only_uses_subprocess_for_selfcheck() -> None:
    users = [p.name for p in files(SERVICE) if imports_of(p) & PROCESS_MODULES]
    assert users == ["selfcheck.py"]  # 起動前の自己検査(netsh・icacls)だけ
