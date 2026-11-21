"""CapabilityAllowlist 集約(data-model.md §3。research.md R12。憲章 S3)。

項目: CapabilityAllowlist.entries(キー → 値の型)、.version。既定は空(すべて拒否)。
申告の検査では、違反の理由にキーと理由だけを使い、申告された値は含めない。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from job_core.job.domain.errors import ValidationFailed

from .errors import InvalidDeclaration
from .values import (
    CAPABILITY_KEY_PATTERN,
    MAX_CAPABILITY_KEYS,
    MAX_SET_ELEMENTS,
    MAX_TEXT_LENGTH,
    Capabilities,
    CapabilityKey,
    CapabilityValue,
    SetValue,
    SingleValue,
    ValueKind,
    has_control_character,
)

NOT_ALLOWED = "not_allowed"
KIND_MISMATCH = "kind_mismatch"
INVALID_KEY = "invalid_key"
INVALID_VALUE = "invalid_value"
TOO_MANY_KEYS = "too_many_keys"
NOT_A_MAPPING = "not_a_mapping"


@dataclass(eq=False)
class CapabilityAllowlist:
    entries: dict[CapabilityKey, ValueKind] = field(default_factory=dict)
    version: int = 0

    def validate(self, declared: object) -> Capabilities:
        """申告が許可リストに合うとき Capabilities を返す。合わなければ InvalidDeclaration(違反をすべて返す)。"""
        if not isinstance(declared, Mapping):
            raise InvalidDeclaration([("", NOT_A_MAPPING)])
        violations: list[tuple[str, str]] = []
        if len(declared) > MAX_CAPABILITY_KEYS:
            violations.append(("", TOO_MANY_KEYS))
        accepted: dict[CapabilityKey, CapabilityValue] = {}
        for key, raw in declared.items():
            key_text = key if isinstance(key, str) else ""
            if not isinstance(key, str) or CAPABILITY_KEY_PATTERN.fullmatch(key) is None:
                violations.append((key_text, INVALID_KEY))
                continue
            allowed_kind = self.entries.get(CapabilityKey(key))
            if allowed_kind is None:
                violations.append((key, NOT_ALLOWED))
                continue
            parsed = _parse_value(raw)
            if parsed is None:
                violations.append((key, INVALID_VALUE))
            elif parsed.kind is not allowed_kind:
                violations.append((key, KIND_MISMATCH))
            else:
                accepted[CapabilityKey(key)] = parsed
        if violations:
            raise InvalidDeclaration(violations)
        return Capabilities(accepted)

    def replace(self, entries: Mapping[str, Any]) -> None:
        """一覧を置き換える(既存のランナーの能力は変えない)。キーの形式・値の型が不正なら ValidationFailed。"""
        if len(entries) > MAX_CAPABILITY_KEYS * 4:
            raise ValidationFailed("entries", "許可するキーが多すぎる")
        replaced: dict[CapabilityKey, ValueKind] = {}
        for key, kind in entries.items():
            if not isinstance(key, str) or CAPABILITY_KEY_PATTERN.fullmatch(key) is None:
                raise ValidationFailed("entries", "能力のキーの形式に合わない")
            try:
                replaced[CapabilityKey(key)] = ValueKind(kind)
            except ValueError:
                raise ValidationFailed("entries", "値の型は single または set でなければならない") from None
        self.entries = replaced


def _parse_value(raw: object) -> CapabilityValue | None:
    """申告の値を CapabilityValue にする。長さ・文字・個数の制限(research.md R2)を満たさなければ None。"""
    if isinstance(raw, str):
        return SingleValue(raw) if _valid_text(raw) else None
    if isinstance(raw, list):
        if len(raw) > MAX_SET_ELEMENTS or not all(_valid_text(e) for e in raw):
            return None
        return SetValue(frozenset(raw))
    return None


def _valid_text(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= MAX_TEXT_LENGTH and not has_control_character(value)
