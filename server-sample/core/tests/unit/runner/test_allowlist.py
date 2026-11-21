"""CapabilityAllowlist の単体テスト(research.md R12。SC-007)。"""

from __future__ import annotations

from typing import Any

import pytest

from job_core.job.domain.errors import ValidationFailed
from job_core.runner.domain.allowlist import CapabilityAllowlist
from job_core.runner.domain.errors import InvalidDeclaration
from job_core.runner.domain.values import ValueKind


def allowlist() -> CapabilityAllowlist:
    result = CapabilityAllowlist()
    result.replace({"k1": "single", "set1": "set"})
    return result


def violations_of(declared: Any, target: CapabilityAllowlist | None = None) -> dict[str, str]:
    with pytest.raises(InvalidDeclaration) as err:
        (target or allowlist()).validate(declared)
    return dict(err.value.violations)


def test_default_is_empty_and_rejects_everything() -> None:
    assert violations_of({"k1": "a"}, CapabilityAllowlist()) == {"k1": "not_allowed"}


def test_empty_declaration_is_accepted_even_with_empty_allowlist() -> None:
    assert len(CapabilityAllowlist().validate({})) == 0


def test_accepts_matching_keys_and_kinds() -> None:
    caps = allowlist().validate({"k1": "a", "set1": ["x", "y"]})
    assert caps.to_json() == {"k1": "a", "set1": ["x", "y"]}


def test_subset_of_allowed_keys_is_fine() -> None:
    assert allowlist().validate({"k1": "a"}).to_json() == {"k1": "a"}


def test_key_outside_list_is_rejected() -> None:
    assert violations_of({"k1": "a", "k9": "z"}) == {"k9": "not_allowed"}


def test_kind_mismatch() -> None:
    assert violations_of({"k1": ["a"], "set1": "x"}) == {"k1": "kind_mismatch", "set1": "kind_mismatch"}


@pytest.mark.parametrize(
    "bad",
    ["", "a" * 257, "a\nb", 5, None, True, {"a": 1}, ["a", ""], ["a", 5], ["x"] * 0 + [f"v{i}" for i in range(65)]],
)
def test_value_limits(bad: Any) -> None:
    key = "set1" if isinstance(bad, list) else "k1"
    assert violations_of({key: bad}) == {key: "invalid_value"}


@pytest.mark.parametrize("bad_key", ["K1", "a b", "", "é", "a" * 65])
def test_invalid_key_form(bad_key: str) -> None:
    assert list(violations_of({bad_key: "a"}).values()) == ["invalid_key"]


def test_non_mapping_declaration() -> None:
    assert violations_of(["k1"]) == {"": "not_a_mapping"}


def test_all_violations_are_reported_together() -> None:
    result = violations_of({"k9": "a", "k1": ["a"], "set1": [""]})
    assert result == {"k9": "not_allowed", "k1": "kind_mismatch", "set1": "invalid_value"}


def test_too_many_keys() -> None:
    wide = CapabilityAllowlist()
    wide.replace({f"k{i}": "single" for i in range(65)})
    result = violations_of({f"k{i}": "a" for i in range(65)}, wide)
    assert result[""] == "too_many_keys"


def test_violations_never_contain_declared_values() -> None:
    secret = "TOP-SECRET-VALUE"
    with pytest.raises(InvalidDeclaration) as err:
        allowlist().validate({"k9": secret, "k1": [secret], "set1": secret})
    assert secret not in repr(err.value.violations)
    assert secret not in str(err.value)
    assert secret not in repr(err.value.details)


def test_long_key_is_shortened_in_violations() -> None:
    long_key = "z" * 500
    with pytest.raises(InvalidDeclaration) as err:
        allowlist().validate({long_key: "a"})
    assert all(len(key) <= 64 for key, _ in err.value.violations)


def test_replace_validates_and_replaces() -> None:
    target = allowlist()
    target.replace({"k2": ValueKind.SINGLE})
    assert dict(target.entries) == {"k2": ValueKind.SINGLE}
    for bad in ({"K": "single"}, {"k1": "list"}, {"k1": 5}):
        with pytest.raises(ValidationFailed):
            target.replace(bad)
    assert dict(target.entries) == {"k2": ValueKind.SINGLE}  # 失敗したら変わらない
