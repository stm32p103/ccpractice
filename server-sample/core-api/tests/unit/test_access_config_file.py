"""TOML の AccessConfigSource(契約テストと不正な設定の試験。research.md R6)。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from job_core_api.access.config import AccessConfigInvalid
from job_core_api.access.config_file import TomlAccessConfigSource
from job_testing.contracts.access_config import VALID, AccessConfigContract, ConfigEnv


def q(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # TOML の基本文字列と同じ引用の形


def to_toml(data: Mapping[str, Any]) -> str:
    """検証前の構造を TOML にする(契約テストの入力用)。"""
    lines = [f"default_roles = {json.dumps(data['default_roles'])}", ""]
    for name, body in data["roles"].items():
        lines += [f"[roles.{q(name)}]", f"permissions = {json.dumps(body['permissions'])}", ""]
    lines.append("[groups]")
    lines += [f"{q(group)} = {json.dumps(roles)}" for group, roles in data["groups"].items()]
    lines += ["", "[service]", f"permission_ceiling = {json.dumps(data['service']['permission_ceiling'])}", ""]
    return "\n".join(lines)


class TestTomlAccessConfigSource(AccessConfigContract):
    @pytest.fixture
    def config_env(self, tmp_path: Path) -> ConfigEnv:
        path = tmp_path / "access.toml"

        def set_config(data: Mapping[str, Any]) -> None:
            path.write_text(to_toml(data), encoding="utf-8")

        return ConfigEnv(source=TomlAccessConfigSource(path), set_config=set_config)


def test_the_file_is_read_on_every_call(tmp_path: Path) -> None:
    path = tmp_path / "access.toml"
    path.write_text(to_toml(VALID), encoding="utf-8")
    source = TomlAccessConfigSource(path)
    first = source.load()
    changed = dict(VALID)
    changed["default_roles"] = []
    path.write_text(to_toml(changed), encoding="utf-8")
    assert source.load().digest != first.digest


def test_missing_file_and_broken_toml_are_invalid_without_excerpts(tmp_path: Path) -> None:
    with pytest.raises(AccessConfigInvalid) as missing:
        TomlAccessConfigSource(tmp_path / "nothing.toml").load()
    assert [v.location for v in missing.value.violations] == ["file"]
    broken = tmp_path / "broken.toml"
    broken.write_text("secret-looking = = value", encoding="utf-8")
    with pytest.raises(AccessConfigInvalid) as invalid:
        TomlAccessConfigSource(broken).load()
    assert "secret-looking" not in str(invalid.value)


def test_directory_instead_of_file_is_invalid(tmp_path: Path) -> None:
    with pytest.raises(AccessConfigInvalid):
        TomlAccessConfigSource(tmp_path).load()
