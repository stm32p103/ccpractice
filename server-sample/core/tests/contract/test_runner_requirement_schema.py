"""ランナー要件・能力の申告の JSON Schema と、実装(照合・許可リスト)の一致の検査(T013。research.md R2、R16)。

- 一致の検査: パッケージ内のスキーマに適合する ⇔ 実装が受け付ける(Hypothesis で生成した値)
- 同一性の検査: パッケージ内のスキーマが、spec の contracts/ のスキーマと内容が同一(specs を読むのは最後の 2 件だけ)
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from job_core.job.domain.values import RunnerRequirement
from job_core.runner.domain.allowlist import CapabilityAllowlist
from job_core.runner.domain.errors import InvalidDeclaration, InvalidRequirement
from job_core.runner.domain.matching import parse_requirement
from job_core.runner.domain.values import ValueKind

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_CONTRACTS = REPO_ROOT / "specs" / "002-runner-management" / "contracts"


def packaged(name: str) -> dict[str, Any]:
    text = resources.files("job_core.runner").joinpath(f"schemas/{name}").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


REQUIREMENT_SCHEMA = packaged("runner_requirement.v1.json")
DECLARATION_SCHEMA = packaged("capability_declaration.v1.json")


def schema_accepts(schema: dict[str, Any], document: Any) -> bool:
    return jsonschema.Draft202012Validator(schema).is_valid(document)


# 改行は含めない(JSON Schema の `$` は末尾の改行の前にも一致する言語があり、検査の対象外にするため)
texts = st.one_of(
    st.text(alphabet="abc0123 .-_", min_size=0, max_size=6),
    st.just("a\x01b"),
    st.just("a\x7fb"),
    st.just("é"),
    st.just("x" * 256),
    st.just("x" * 257),
)
keys = st.sampled_from(["k1", "set1", "a", "0x", "K1", "k 1", "", "é", "a" * 64, "a" * 65, "-a", "a.b_c-d"])
numbers = st.sampled_from(["0", "1", "-1", "1.5", "-0.25", "abc", "1e3", "1.", ".5", "", "０５"])
versions = st.sampled_from(["1", "1.2", "1.2.3", "1.2.3.4.5.6.7.8", "1.2.3.4.5.6.7.8.9", "1..2", "v1", "1.2-rc", ""])
op_names = st.sampled_from(
    [
        "eq",
        "in",
        "contains",
        "num_gt",
        "num_ge",
        "num_lt",
        "num_le",
        "ver_gt",
        "ver_ge",
        "ver_lt",
        "ver_le",
        "regex",
        "",
    ]
)
scalars = st.one_of(texts, numbers, versions, st.integers(), st.none(), st.booleans())
lists = st.lists(st.one_of(texts, st.integers()), max_size=3)


@st.composite
def conditions(draw: st.DrawFn) -> Any:
    shape = draw(st.integers(min_value=0, max_value=9))
    if shape == 0:
        return draw(st.one_of(st.integers(), st.none(), st.text(max_size=3)))
    condition: dict[str, Any] = {"key": draw(keys), "op": draw(op_names)}
    if shape in (1, 2, 3):
        condition["value"] = draw(st.one_of(texts, scalars))
    elif shape == 4:
        condition["values"] = draw(lists)
    elif shape == 5:
        condition["value"] = draw(numbers)
    elif shape == 6:
        condition["value"] = draw(versions)
    elif shape == 7:
        condition["values"] = draw(st.lists(texts, min_size=1, max_size=3))
    elif shape == 8:
        condition["value"] = draw(texts)
        condition["values"] = draw(lists)
    if draw(st.integers(min_value=0, max_value=14)) == 0:
        condition["extra"] = 1
    if draw(st.integers(min_value=0, max_value=14)) == 0:
        condition.pop(draw(st.sampled_from(["key", "op"])), None)
    return condition


@st.composite
def good_conditions(draw: st.DrawFn) -> dict[str, Any]:
    op = draw(st.sampled_from(["eq", "in", "contains", "num_gt", "num_le", "ver_ge", "ver_lt"]))
    key = draw(st.sampled_from(["k1", "set1", "a.b"]))
    if op in ("in", "contains"):
        values = draw(st.lists(st.sampled_from(["a", "b", "c"]), min_size=1, max_size=3))
        return {"key": key, "op": op, "values": values}
    if op.startswith("num"):
        return {"key": key, "op": op, "value": draw(st.sampled_from(["1", "-2.5", "10"]))}
    if op.startswith("ver"):
        return {"key": key, "op": op, "value": draw(st.sampled_from(["1", "1.2", "1.2.3"]))}
    return {"key": key, "op": op, "value": "a"}


requirements = st.one_of(
    st.builds(lambda items: {"all": items}, st.lists(st.one_of(conditions(), good_conditions()), max_size=3)),
    st.builds(lambda items: {"all": items}, st.lists(good_conditions(), max_size=4)),
    st.builds(lambda items: {"all": items, "extra": 1}, st.lists(good_conditions(), max_size=1)),
    st.sampled_from([{}, [], {"all": None}, {"all": "x"}, {"other": []}]),
)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(requirements)
def test_requirement_schema_matches_parser(document: Any) -> None:
    try:
        parse_requirement(RunnerRequirement.of(document))
        parser_accepts = True
    except InvalidRequirement:
        parser_accepts = False
    assert schema_accepts(REQUIREMENT_SCHEMA, document) is parser_accepts


def test_requirement_schema_examples_parse() -> None:
    for example in REQUIREMENT_SCHEMA["examples"]:
        assert schema_accepts(REQUIREMENT_SCHEMA, example)
        parse_requirement(RunnerRequirement.of(example))


def test_requirement_schema_condition_limit() -> None:
    many = {"all": [{"key": "k1", "op": "eq", "value": "a"}] * 65}
    assert not schema_accepts(REQUIREMENT_SCHEMA, many)
    with pytest.raises(InvalidRequirement):
        parse_requirement(RunnerRequirement.of(many))


# ---------------------------------------------------------------------- 能力の申告

declared_values = st.one_of(
    texts,
    st.lists(texts, max_size=3),
    st.lists(st.sampled_from(["x", "y", "z"]), max_size=3),
    st.integers(),
    st.none(),
    st.lists(st.integers(), max_size=2),
    st.dictionaries(st.text(max_size=2), st.text(max_size=2), max_size=1),
)
declarations = st.one_of(
    st.dictionaries(keys, declared_values, max_size=4),
    st.just({f"k{i}": "a" for i in range(64)}),
    st.just({f"k{i}": "a" for i in range(65)}),
    st.sampled_from([[], "x", None, 5]),
)


def permissive_allowlist_for(declaration: Any) -> CapabilityAllowlist:
    """申告に現れるキーを、申告の値の型のとおりに許可する(許可リストの判定を、形の検査から切り離すため)。"""
    allowlist = CapabilityAllowlist()
    if isinstance(declaration, dict):
        entries = {
            key: (ValueKind.SET if isinstance(value, list) else ValueKind.SINGLE)
            for key, value in declaration.items()
            if isinstance(key, str) and key and key.isascii() and key == key.lower() and " " not in key
        }
        entries = {k: v for k, v in entries.items() if _is_key(k)}
        allowlist.replace(entries)
    return allowlist


def _is_key(key: str) -> bool:
    return re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", key) is not None


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(declarations)
def test_declaration_schema_matches_validator_shape(declaration: Any) -> None:
    allowlist = permissive_allowlist_for(declaration)
    try:
        allowlist.validate(declaration)
        validator_accepts = True
    except InvalidDeclaration:
        validator_accepts = False
    assert schema_accepts(DECLARATION_SCHEMA, declaration) is validator_accepts


def test_declaration_schema_examples_validate() -> None:
    for example in DECLARATION_SCHEMA["examples"]:
        assert schema_accepts(DECLARATION_SCHEMA, example)
        permissive_allowlist_for(example).validate(example)


# ---------------------------------------------------------------------- 同一性


@pytest.mark.parametrize(
    ("packaged_name", "spec_name"),
    [
        ("runner_requirement.v1.json", "runner-requirement.schema.json"),
        ("capability_declaration.v1.json", "capability-declaration.schema.json"),
    ],
)
def test_packaged_schema_is_identical_to_spec_contract(packaged_name: str, spec_name: str) -> None:
    assert packaged(packaged_name) == json.loads((SPEC_CONTRACTS / spec_name).read_text(encoding="utf-8"))
