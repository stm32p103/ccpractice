"""AccessConfig の検証と導出(data-model.md §2、research.md R6)。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from job_core.access.permission import Permission as P
from job_core_api.access.config import AccessConfig, AccessConfigInvalid
from job_testing.contracts.access_config import VALID, variant

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "specs/003-core-api/contracts/access-config.schema.json").read_text("utf-8")
)


def build(data: dict[str, Any]) -> AccessConfig:
    return AccessConfig.from_mapping(data)


def test_valid_config_conforms_to_the_json_schema() -> None:
    jsonschema.validate(VALID, SCHEMA)
    build(VALID)


def test_union_of_roles_over_multiple_groups() -> None:
    config = build(VALID)
    assert config.permissions_of({"g-members", "g-admins"}) >= {P.ACCESS_MANAGE, P.JOB_SUBMIT}


def test_no_matching_group_uses_default_roles_and_matching_does_not_add_them() -> None:
    data = variant(default_roles=["viewer"], groups={"g": ["member"]})
    config = build(data)
    assert config.permissions_of({"other"}) == {P.GENERAL}
    assert config.permissions_of({"g", "other"}) == {P.GENERAL, P.JOB_SUBMIT}
    empty_default = build(variant(default_roles=[]))
    assert empty_default.permissions_of({"other"}) == frozenset()


@pytest.mark.parametrize("permission", ["job.execute", "runner.report", "retention.purge", "runner.sweep"])
def test_non_role_permissions_are_rejected(permission: str) -> None:
    data = variant(roles={"r": {"permissions": [permission]}}, groups={}, default_roles=[])
    with pytest.raises(AccessConfigInvalid):
        build(data)


@pytest.mark.parametrize("permission", ["runner.manage", "access.manage", "audit.read_all", "job.execute"])
def test_service_ceiling_cannot_contain_admin_or_non_role_permissions(permission: str) -> None:
    with pytest.raises(AccessConfigInvalid):
        build(variant(service={"permission_ceiling": [permission]}))


def test_undefined_role_reference_in_groups_and_default_roles() -> None:
    with pytest.raises(AccessConfigInvalid):
        build(variant(groups={"g": ["nope"]}))
    with pytest.raises(AccessConfigInvalid):
        build(variant(default_roles=["nope"]))


def test_unknown_permission_name_and_bad_role_name_are_rejected() -> None:
    with pytest.raises(AccessConfigInvalid):
        build(variant(roles={"r": {"permissions": ["no.such"]}}, groups={}, default_roles=[]))
    with pytest.raises(AccessConfigInvalid):
        build(variant(roles={"Bad Name": {"permissions": []}}, groups={}, default_roles=[]))


def test_unknown_top_level_key_and_missing_keys_are_rejected() -> None:
    data = dict(VALID)
    data["extra"] = 1
    with pytest.raises(AccessConfigInvalid):
        build(data)
    with pytest.raises(AccessConfigInvalid) as info:
        AccessConfig.from_mapping({})
    assert len(info.value.violations) >= 3


def test_digest_is_independent_of_order_and_changes_with_content() -> None:
    a = build(VALID)
    reordered = variant()
    reordered["roles"] = dict(reversed(list(VALID["roles"].items())))
    assert build(reordered).digest == a.digest
    assert build(variant(default_roles=[])).digest != a.digest


def test_violations_hold_only_locations_and_reasons() -> None:
    needle = "needle-value-xyz"
    with pytest.raises(AccessConfigInvalid) as info:
        build(variant(groups={"g": [needle]}))
    assert needle not in str(info.value)
