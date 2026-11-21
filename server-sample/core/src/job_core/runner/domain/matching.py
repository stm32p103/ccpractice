"""要件と能力の照合(research.md R2、R3。FR-007〜FR-009)。

純粋関数だけを置く。判定(any_registered_runner_may_satisfy)と割り当て(RequestJob)は、
どちらも parse_requirement と satisfies だけを使う(FR-009、SC-001)。

- 要件の側の文法の誤り(未知の op、指定値の形の不一致、数値・版として解釈できない値)は InvalidRequirement。
- 能力の側の型の不一致(キーがない、1 つの値に contains、集合に eq、数値でない値に num_*)は、条件を満たさない。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache

from job_core.job.domain.values import RunnerRequirement

from .errors import InvalidRequirement
from .values import (
    CAPABILITY_KEY_PATTERN,
    MAX_SET_ELEMENTS,
    MAX_TEXT_LENGTH,
    Capabilities,
    CapabilityKey,
    SetValue,
    SingleValue,
    has_control_character,
)

MAX_CONDITIONS = 64
MAX_VERSION_SEGMENTS = 8

_NUMBER_PATTERN = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_VERSION_PATTERN = re.compile(r"[0-9]+(\.[0-9]+){0,7}")

VersionTuple = tuple[int, ...]


class Op(StrEnum):
    EQ = "eq"
    IN = "in"
    NUM_GT = "num_gt"
    NUM_GE = "num_ge"
    NUM_LT = "num_lt"
    NUM_LE = "num_le"
    VER_GT = "ver_gt"
    VER_GE = "ver_ge"
    VER_LT = "ver_lt"
    VER_LE = "ver_le"
    CONTAINS = "contains"


_NUMERIC_OPS = {Op.NUM_GT, Op.NUM_GE, Op.NUM_LT, Op.NUM_LE}
_VERSION_OPS = {Op.VER_GT, Op.VER_GE, Op.VER_LT, Op.VER_LE}

Operand = str | frozenset[str] | Decimal | VersionTuple


@dataclass(frozen=True)
class Condition:
    """条件 1 つ(能力のキー、比較の種類、比較する値)。"""

    key: CapabilityKey
    op: Op
    operand: Operand


ParsedRequirement = tuple[Condition, ...]


# ---------------------------------------------------------------------- 文法の検査


def parse_requirement(requirement: RunnerRequirement) -> ParsedRequirement:
    """要件の JSON を、検査済みの条件の並びにする。文法に合わなければ InvalidRequirement。

    正準化済みの JSON 文字列を鍵にメモ化する(待機中のジョブの走査で毎回解析しないため。R11)。
    """
    return _parse_canonical(requirement.canonical_json)


@lru_cache(maxsize=4096)
def _parse_canonical(canonical_json: str) -> ParsedRequirement:
    document = json.loads(canonical_json)
    if not isinstance(document, dict) or set(document) != {"all"}:
        raise InvalidRequirement("要件は all だけを持つオブジェクトでなければならない")
    conditions = document["all"]
    if not isinstance(conditions, list):
        raise InvalidRequirement("all は条件の配列でなければならない")
    if len(conditions) > MAX_CONDITIONS:
        raise InvalidRequirement(f"条件は {MAX_CONDITIONS} 個以内でなければならない")
    return tuple(_parse_condition(raw, index) for index, raw in enumerate(conditions))


def _parse_condition(raw: object, index: int) -> Condition:
    where = f"all[{index}]"
    if not isinstance(raw, dict):
        raise InvalidRequirement(f"{where}: 条件はオブジェクトでなければならない")
    key = raw.get("key")
    if not isinstance(key, str) or CAPABILITY_KEY_PATTERN.fullmatch(key) is None:
        raise InvalidRequirement(f"{where}: key が能力のキーの形式に合わない")
    op_text = raw.get("op")
    try:
        op = Op(op_text)  # type: ignore[arg-type]
    except ValueError:
        raise InvalidRequirement(f"{where}: 未知の比較の種類") from None
    if op in (Op.IN, Op.CONTAINS):
        _require_keys(raw, {"key", "op", "values"}, where)
        return Condition(CapabilityKey(key), op, _parse_texts(raw["values"], where))
    _require_keys(raw, {"key", "op", "value"}, where)
    value = raw["value"]
    if op is Op.EQ:
        return Condition(CapabilityKey(key), op, _parse_text(value, where))
    if op in _NUMERIC_OPS:
        if not isinstance(value, str) or _NUMBER_PATTERN.fullmatch(value) is None:
            raise InvalidRequirement(f"{where}: value が数値として解釈できない")
        return Condition(CapabilityKey(key), op, Decimal(value))
    if not isinstance(value, str) or (version := parse_version(value)) is None:
        raise InvalidRequirement(f"{where}: value が版として解釈できない")
    return Condition(CapabilityKey(key), op, version)


def _require_keys(raw: dict[str, object], expected: set[str], where: str) -> None:
    if set(raw) != expected:
        raise InvalidRequirement(f"{where}: 条件の項目が比較の種類に合わない")


def _parse_text(value: object, where: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_TEXT_LENGTH or has_control_character(value):
        raise InvalidRequirement(f"{where}: 指定値は 1〜{MAX_TEXT_LENGTH} 文字の文字列でなければならない")
    return value


def _parse_texts(value: object, where: str) -> frozenset[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SET_ELEMENTS:
        raise InvalidRequirement(f"{where}: values は 1〜{MAX_SET_ELEMENTS} 個の文字列の配列でなければならない")
    return frozenset(_parse_text(element, where) for element in value)


def parse_version(text: str) -> VersionTuple | None:
    """版の文字列を整数の並びにする。版として解釈できなければ None。"""
    if _VERSION_PATTERN.fullmatch(text) is None:
        return None
    return tuple(int(part) for part in text.split("."))


def parse_number(text: str) -> Decimal | None:
    """数値の文字列を Decimal にする。数値として解釈できなければ None。"""
    if _NUMBER_PATTERN.fullmatch(text) is None:
        return None
    return Decimal(text)


# ---------------------------------------------------------------------- 照合


def satisfies(capabilities: Capabilities, requirement: ParsedRequirement) -> bool:
    """すべての条件を満たすとき真。空の要件はすべての能力が満たす。"""
    return all(_holds(capabilities, condition) for condition in requirement)


def compare_versions(left: VersionTuple, right: VersionTuple) -> int:
    """版の大小(-1 / 0 / 1)。短い方の末尾を 0 で補う(1.2 = 1.2.0)。"""
    size = max(len(left), len(right))
    a = left + (0,) * (size - len(left))
    b = right + (0,) * (size - len(right))
    return (a > b) - (a < b)


def _holds(capabilities: Capabilities, condition: Condition) -> bool:
    value = capabilities.get(condition.key)
    if value is None:
        return False  # 要件に指定したキーを能力として持たない
    op = condition.op
    operand = condition.operand
    if op is Op.CONTAINS:
        return isinstance(value, SetValue) and isinstance(operand, frozenset) and operand <= value.values
    if not isinstance(value, SingleValue):
        return False  # 集合に、1 つの値の比較は当てはまらない
    if op is Op.EQ:
        return value.value == operand
    if op is Op.IN:
        return isinstance(operand, frozenset) and value.value in operand
    if op in _NUMERIC_OPS:
        number = parse_number(value.value)
        if number is None or not isinstance(operand, Decimal):
            return False
        return _decide(op, (number > operand) - (number < operand))
    version = parse_version(value.value)
    if version is None or not isinstance(operand, tuple):
        return False
    return _decide(op, compare_versions(version, operand))


def _decide(op: Op, ordering: int) -> bool:
    if op in (Op.NUM_GT, Op.VER_GT):
        return ordering > 0
    if op in (Op.NUM_GE, Op.VER_GE):
        return ordering >= 0
    if op in (Op.NUM_LT, Op.VER_LT):
        return ordering < 0
    return ordering <= 0
