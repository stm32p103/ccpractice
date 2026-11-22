"""AccessConfigSource のポートの契約テスト(contracts/ports.md「AccessConfigSource」)。

使い方: テストのクラスで継承し、`config_env` フィクスチャ(ConfigEnv)を定義する。
`set_config` は、検証前の構造(TOML を読んだ後の辞書)を設定として与える。
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pytest

from job_core.access.permission import Permission
from job_core_api.access.config import AccessConfigInvalid
from job_core_api.access.ports import AccessConfigSource

VALID: dict[str, Any] = {
    "roles": {
        "viewer": {"permissions": ["job.general"]},
        "member": {"permissions": ["job.general", "job.submit"]},
        "admin": {"permissions": ["job.general", "job.submit", "audit.read_all", "runner.manage", "access.manage"]},
    },
    "groups": {"g-members": ["member"], "g-admins": ["admin", "member"]},
    "default_roles": ["viewer"],
    "service": {"permission_ceiling": ["job.submit", "job.general", "job.submit_on_behalf"]},
}


@dataclass
class ConfigEnv:
    source: AccessConfigSource
    set_config: Callable[[Mapping[str, Any]], None]


def variant(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(VALID)
    data.update(changes)
    return data


class AccessConfigContract:
    def test_valid_config_loads_and_derives_permissions(self, config_env: ConfigEnv) -> None:
        config_env.set_config(VALID)
        config = config_env.source.load()
        assert config.permissions_of({"g-members"}) == {Permission.GENERAL, Permission.JOB_SUBMIT}
        assert config.permissions_of({"unknown"}) == {Permission.GENERAL}
        assert Permission.ACCESS_MANAGE in config.permissions_of({"g-admins", "g-members"})

    def test_undefined_role_is_rejected(self, config_env: ConfigEnv) -> None:
        config_env.set_config(variant(groups={"g": ["nonexistent"]}))
        with pytest.raises(AccessConfigInvalid) as info:
            config_env.source.load()
        assert any("未定義" in v.reason for v in info.value.violations)

    def test_permission_that_cannot_be_on_a_role_is_rejected(self, config_env: ConfigEnv) -> None:
        bad = variant(roles={"r": {"permissions": ["job.execute"]}}, groups={}, default_roles=[])
        config_env.set_config(bad)
        with pytest.raises(AccessConfigInvalid):
            config_env.source.load()

    def test_permission_outside_the_service_ceiling_set_is_rejected(self, config_env: ConfigEnv) -> None:
        config_env.set_config(variant(service={"permission_ceiling": ["access.manage"]}))
        with pytest.raises(AccessConfigInvalid):
            config_env.source.load()

    def test_violations_do_not_contain_config_excerpts(self, config_env: ConfigEnv) -> None:
        secret_like = "SECRET-LIKE-VALUE-123"
        config_env.set_config(variant(groups={"g": [secret_like]}))
        with pytest.raises(AccessConfigInvalid) as info:
            config_env.source.load()
        assert secret_like not in str(info.value)
        assert all(secret_like not in v.reason and secret_like not in v.location for v in info.value.violations)

    def test_digest_is_stable_regardless_of_order(self, config_env: ConfigEnv) -> None:
        config_env.set_config(VALID)
        first = config_env.source.load().digest
        reordered = copy.deepcopy(VALID)
        reordered["roles"] = dict(reversed(list(VALID["roles"].items())))
        reordered["roles"]["admin"]["permissions"] = list(reversed(VALID["roles"]["admin"]["permissions"]))
        reordered["groups"] = dict(reversed(list(VALID["groups"].items())))
        config_env.set_config(reordered)
        assert config_env.source.load().digest == first
        changed = variant(default_roles=[])
        config_env.set_config(changed)
        assert config_env.source.load().digest != first
