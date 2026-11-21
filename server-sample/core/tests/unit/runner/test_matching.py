"""照合の単体テスト(research.md R2、R16。SC-001)。

5 種の比較(Op の全値)× 1 つの値/集合 × キーの有無 × 能力側の型の不一致、要件側の文法のエラー、
版・数値の比較の性質(Hypothesis)。キーは記号(k1、set1)を使う。
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from job_core.job.domain.values import RunnerRequirement
from job_core.runner.domain.errors import InvalidRequirement
from job_core.runner.domain.matching import Op, compare_versions, parse_requirement, parse_version, satisfies
from job_core.runner.domain.values import Capabilities


def req(*conditions: dict[str, Any]) -> RunnerRequirement:
    return RunnerRequirement.of({"all": list(conditions)})


def holds(caps: dict[str, Any], *conditions: dict[str, Any]) -> bool:
    return satisfies(Capabilities.of(caps), parse_requirement(req(*conditions)))


def cond(op: str, value: Any, key: str = "k1") -> dict[str, Any]:
    field = "values" if op in ("in", "contains") else "value"
    return {"key": key, "op": op, field: value}


class TestEmptyAndMissing:
    def test_empty_requirement_is_satisfied_by_everyone(self) -> None:
        assert holds({})
        assert holds({"k1": "a"})

    def test_missing_key_does_not_satisfy_any_op(self) -> None:
        samples = {
            "eq": "a",
            "in": ["a"],
            "num_gt": "1",
            "num_ge": "1",
            "num_lt": "1",
            "num_le": "1",
            "ver_gt": "1",
            "ver_ge": "1",
            "ver_lt": "1",
            "ver_le": "1",
            "contains": ["a"],
        }
        assert set(samples) == {op.value for op in Op}
        for op, value in samples.items():
            assert not holds({"other": "a"}, cond(op, value)), op

    def test_all_conditions_must_hold(self) -> None:
        caps = {"k1": "a", "k2": "5"}
        assert holds(caps, cond("eq", "a"), cond("num_ge", "5", "k2"))
        assert not holds(caps, cond("eq", "a"), cond("num_ge", "6", "k2"))


class TestEqAndIn:
    def test_eq(self) -> None:
        assert holds({"k1": "a"}, cond("eq", "a"))
        assert not holds({"k1": "a"}, cond("eq", "b"))

    def test_in(self) -> None:
        assert holds({"k1": "b"}, cond("in", ["a", "b"]))
        assert not holds({"k1": "c"}, cond("in", ["a", "b"]))

    def test_set_value_never_satisfies_single_value_ops(self) -> None:
        caps = {"k1": ["a"]}
        assert not holds(caps, cond("eq", "a"))
        assert not holds(caps, cond("in", ["a"]))
        assert not holds(caps, cond("num_ge", "0"))
        assert not holds(caps, cond("ver_ge", "0"))


class TestNumeric:
    @pytest.mark.parametrize(
        ("op", "value", "expected"),
        [
            ("num_gt", "4", True),
            ("num_gt", "5", False),
            ("num_ge", "5", True),
            ("num_ge", "5.1", False),
            ("num_lt", "6", True),
            ("num_lt", "5", False),
            ("num_le", "5", True),
            ("num_le", "4.9", False),
            ("num_ge", "5.0", True),
        ],
    )
    def test_compare(self, op: str, value: str, expected: bool) -> None:
        assert holds({"k1": "5"}, cond(op, value)) is expected

    def test_decimal_has_no_float_error(self) -> None:
        assert holds({"k1": "0.3"}, cond("num_le", "0.3"))
        assert holds({"k1": "0.1"}, cond("num_lt", "0.2"))

    def test_negative_numbers(self) -> None:
        assert holds({"k1": "-2"}, cond("num_lt", "-1"))
        assert not holds({"k1": "-2"}, cond("num_gt", "-1"))

    @pytest.mark.parametrize("not_number", ["abc", "1e3", "1,5", "", "5 ", "０５"])
    def test_non_numeric_capability_does_not_satisfy(self, not_number: str) -> None:
        caps = {"k1": not_number} if not_number else {}
        assert not holds(caps, cond("num_ge", "0"))


class TestVersion:
    @pytest.mark.parametrize(
        ("have", "op", "want", "expected"),
        [
            ("1.2.3", "ver_gt", "1.2.2", True),
            ("1.2.3", "ver_gt", "1.2.3", False),
            ("1.2.3", "ver_ge", "1.2.3", True),
            ("1.10", "ver_gt", "1.9", True),  # 数の並びとして比べる(文字列の順ではない)
            ("1.2", "ver_ge", "1.2.0", True),  # 末尾の 0 の補い
            ("1.2.0", "ver_le", "1.2", True),
            ("1.2", "ver_lt", "1.2.0.1", True),
            ("2", "ver_gt", "1.99.99", True),
            ("1.2.3", "ver_lt", "1.2.4", True),
            ("1.2.3", "ver_le", "1.2.2", False),
        ],
    )
    def test_compare(self, have: str, op: str, want: str, expected: bool) -> None:
        assert holds({"k1": have}, cond(op, want)) is expected

    @pytest.mark.parametrize("bad", ["1.2-rc1", "v1.2", "1..2", "1.", ".1", "1.2.3.4.5.6.7.8.9", "abc"])
    def test_non_version_capability_does_not_satisfy(self, bad: str) -> None:
        assert not holds({"k1": bad}, cond("ver_ge", "0"))


class TestContains:
    def test_all_values_must_be_included(self) -> None:
        caps = {"set1": ["x", "y", "z"]}
        assert holds(caps, cond("contains", ["y"], "set1"))
        assert holds(caps, cond("contains", ["x", "z"], "set1"))
        assert not holds(caps, cond("contains", ["x", "w"], "set1"))

    def test_single_value_never_contains(self) -> None:
        assert not holds({"set1": "x"}, cond("contains", ["x"], "set1"))

    def test_empty_set_contains_nothing(self) -> None:
        assert not holds({"set1": []}, cond("contains", ["x"], "set1"))


class TestGrammarErrors:
    @pytest.mark.parametrize(
        "document",
        [
            [],
            {},
            {"all": "x"},
            {"all": [], "extra": 1},
            {"all": [1]},
            {"all": [{"key": "K", "op": "eq", "value": "a"}]},  # キーの形式
            {"all": [{"key": "k1", "op": "regex", "value": "a"}]},  # 未知の op
            {"all": [{"key": "k1", "op": "eq"}]},
            {"all": [{"key": "k1", "op": "eq", "value": "a", "values": ["a"]}]},
            {"all": [{"key": "k1", "op": "eq", "value": ""}]},
            {"all": [{"key": "k1", "op": "eq", "value": 5}]},
            {"all": [{"key": "k1", "op": "in", "values": []}]},
            {"all": [{"key": "k1", "op": "in", "value": "a"}]},
            {"all": [{"key": "k1", "op": "contains", "values": "a"}]},
            {"all": [{"key": "k1", "op": "num_gt", "value": "abc"}]},
            {"all": [{"key": "k1", "op": "num_gt", "value": 5}]},
            {"all": [{"key": "k1", "op": "ver_gt", "value": "1.2-rc1"}]},
            {"all": [{"key": "k1", "op": "ver_gt", "value": "1.2.3.4.5.6.7.8.9"}]},
            {"all": [{"key": "k1", "op": "eq", "value": "a\nb"}]},
        ],
    )
    def test_invalid_requirement(self, document: Any) -> None:
        with pytest.raises(InvalidRequirement) as err:
            parse_requirement(RunnerRequirement.of(document))
        assert err.value.reason

    def test_condition_limit(self) -> None:
        many = [{"key": "k1", "op": "eq", "value": "a"}] * 64
        parse_requirement(RunnerRequirement.of({"all": many}))
        with pytest.raises(InvalidRequirement):
            parse_requirement(RunnerRequirement.of({"all": [*many, many[0]]}))

    def test_error_does_not_echo_values(self) -> None:
        with pytest.raises(InvalidRequirement) as err:
            parse_requirement(RunnerRequirement.of({"all": [{"key": "k1", "op": "num_gt", "value": "SECRET-VALUE"}]}))
        assert "SECRET-VALUE" not in err.value.reason

    def test_parse_is_memoized_by_canonical_form(self) -> None:
        a = parse_requirement(RunnerRequirement.of({"all": [{"op": "eq", "key": "k1", "value": "a"}]}))
        b = parse_requirement(RunnerRequirement.of({"all": [{"key": "k1", "value": "a", "op": "eq"}]}))
        assert a is b


# ---------------------------------------------------------------------- 性質(Hypothesis)

versions = st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=8).map(tuple)


@given(versions)
def test_version_compare_is_reflexive(v: tuple[int, ...]) -> None:
    assert compare_versions(v, v) == 0


@given(versions, versions)
def test_version_compare_is_antisymmetric(a: tuple[int, ...], b: tuple[int, ...]) -> None:
    assert compare_versions(a, b) == -compare_versions(b, a)


@given(versions, versions, versions)
def test_version_compare_is_transitive(a: tuple[int, ...], b: tuple[int, ...], c: tuple[int, ...]) -> None:
    if compare_versions(a, b) <= 0 and compare_versions(b, c) <= 0:
        assert compare_versions(a, c) <= 0


@given(versions, st.integers(min_value=0, max_value=3))
def test_trailing_zeros_do_not_change_order(v: tuple[int, ...], zeros: int) -> None:
    assert compare_versions(v, v + (0,) * zeros) == 0
    assert len(v) + zeros > 8 or parse_version(".".join(map(str, v + (0,) * zeros))) is not None


decimals = st.decimals(allow_nan=False, allow_infinity=False, min_value=-(10**6), max_value=10**6, places=3).map(str)


@given(decimals, decimals)
def test_number_ops_are_consistent(a: str, b: str) -> None:
    caps = {"k1": a}

    def check(op: str) -> bool:
        return holds(caps, cond(op, b))

    assert check("num_gt") == (not check("num_le"))
    assert check("num_lt") == (not check("num_ge"))
    assert (check("num_le") and check("num_ge")) == (not check("num_gt") and not check("num_lt"))


@given(st.lists(st.text(alphabet="abc", min_size=1, max_size=3), min_size=1, max_size=5, unique=True))
def test_contains_is_subset_relation(values: list[str]) -> None:
    caps = {"set1": values}
    assert holds(caps, cond("contains", values, "set1"))
    assert holds(caps, cond("contains", values[:1], "set1"))
    assert not holds(caps, cond("contains", [*values, "zzz"], "set1"))
