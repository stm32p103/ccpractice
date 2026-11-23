"""許可リスト(T016。既定は拒否)。"""

from __future__ import annotations

import pytest

from job_runner_agent.guard.allowlist import NotAllowed, RepositoryAllowlist, ToolRegistry
from job_runner_agent.settings import ToolSettings


def test_repository_allowlist_default_denies() -> None:
    assert not RepositoryAllowlist([]).is_allowed("repo-1")
    assert not RepositoryAllowlist(["repo-1"]).is_allowed(None)
    assert RepositoryAllowlist(["repo-1"]).is_allowed("repo-1")
    assert not RepositoryAllowlist(["repo-1"]).is_allowed("repo-1/")


def test_tool_registry_requires_registration_and_permission() -> None:
    registry = ToolRegistry({"a": ToolSettings("C:\\t\\a.exe")})
    assert registry.resolve("a", ["a"]).path == "C:\\t\\a.exe"
    with pytest.raises(NotAllowed):
        registry.resolve("a", [])  # このエグゼキュータに許可されていない
    with pytest.raises(NotAllowed):
        registry.resolve("b", ["b"])  # 登録簿にない
    with pytest.raises(NotAllowed) as info:
        registry.resolve("C:\\evil.exe", ["C:\\evil.exe"])
    assert "evil" not in str(info.value)
