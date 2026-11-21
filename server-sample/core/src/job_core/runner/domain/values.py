"""runner コンテキストの値オブジェクト(data-model.md §1)。

各値の制約は data-model.md を正とする。違反は 001 の ValidationFailed(field, detail)。
TokenHash は repr・str に値を出さない(トークンのハッシュを表示・記録に残さないため。SC-008)。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any, NewType

from job_core.job.domain.errors import ValidationFailed

CAPABILITY_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
MAX_CAPABILITY_KEYS = 64
MAX_SET_ELEMENTS = 64
MAX_TEXT_LENGTH = 256
MAX_FAULT_DESCRIPTION_LENGTH = 200
MAX_RUNNER_NAME_LENGTH = 128
_TOKEN_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


def has_control_character(text: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in text)


def validate_text(value: object, field_name: str) -> str:
    """値の文字列(1〜256 文字、制御文字なし)。"""
    if not isinstance(value, str):
        raise ValidationFailed(field_name, "文字列でなければならない")
    if not 1 <= len(value) <= MAX_TEXT_LENGTH:
        raise ValidationFailed(field_name, f"1〜{MAX_TEXT_LENGTH} 文字でなければならない")
    if has_control_character(value):
        raise ValidationFailed(field_name, "制御文字を含んではならない")
    return value


# ---------------------------------------------------------------------- ランナーの名前


@dataclass(frozen=True)
class RunnerName:
    """ランナーの名前。前後の空白を除いて 1〜128 文字、制御文字なし。"""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ValidationFailed("name", "文字列でなければならない")
        stripped = self.value.strip()
        if not 1 <= len(stripped) <= MAX_RUNNER_NAME_LENGTH:
            raise ValidationFailed("name", f"前後の空白を除いて 1〜{MAX_RUNNER_NAME_LENGTH} 文字でなければならない")
        if has_control_character(stripped):
            raise ValidationFailed("name", "制御文字を含んではならない")
        object.__setattr__(self, "value", stripped)

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------- 能力

CapabilityKey = NewType("CapabilityKey", str)


def parse_capability_key(value: object, field_name: str = "capability_key") -> CapabilityKey:
    if not isinstance(value, str) or CAPABILITY_KEY_PATTERN.fullmatch(value) is None:
        raise ValidationFailed(field_name, "能力のキーの形式(英小文字・数字・._-、64 文字以内)に合わない")
    return CapabilityKey(value)


class ValueKind(StrEnum):
    """許可リストが持つ、能力の値の型。"""

    SINGLE = "single"
    SET = "set"


@dataclass(frozen=True)
class SingleValue:
    """1 つの値(文字列。数値・版も文字列として持つ)。"""

    value: str

    def __post_init__(self) -> None:
        validate_text(self.value, "capability_value")

    @property
    def kind(self) -> ValueKind:
        return ValueKind.SINGLE

    def to_json(self) -> str:
        return self.value


@dataclass(frozen=True)
class SetValue:
    """値の集合(0〜64 要素。重複は 1 つにまとめる)。"""

    values: frozenset[str]

    def __post_init__(self) -> None:
        values = frozenset(self.values)
        if len(values) > MAX_SET_ELEMENTS:
            raise ValidationFailed("capability_value", f"集合は {MAX_SET_ELEMENTS} 要素以内でなければならない")
        for element in values:
            validate_text(element, "capability_value")
        object.__setattr__(self, "values", values)

    @property
    def kind(self) -> ValueKind:
        return ValueKind.SET

    def to_json(self) -> list[str]:
        return sorted(self.values)


CapabilityValue = SingleValue | SetValue


def capability_value_of(raw: object) -> CapabilityValue:
    """申告の値(文字列、または文字列の並び)から CapabilityValue を作る。"""
    if isinstance(raw, SingleValue | SetValue):
        return raw
    if isinstance(raw, str):
        return SingleValue(raw)
    if isinstance(raw, list | tuple | set | frozenset):
        elements = list(raw)
        for element in elements:
            validate_text(element, "capability_value")
        return SetValue(frozenset(elements))
    raise ValidationFailed("capability_value", "文字列、または文字列の集合でなければならない")


@dataclass(frozen=True)
class Capabilities:
    """ランナーの能力(キー → 値)。不変。キーは最大 64 個。"""

    items: dict[CapabilityKey, CapabilityValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.items) > MAX_CAPABILITY_KEYS:
            raise ValidationFailed("capabilities", f"キーは {MAX_CAPABILITY_KEYS} 個以内でなければならない")
        normalized = {parse_capability_key(k): capability_value_of(v) for k, v in self.items.items()}
        object.__setattr__(self, "items", normalized)

    @classmethod
    def of(cls, mapping: Mapping[str, Any]) -> Capabilities:
        return cls({parse_capability_key(k): capability_value_of(v) for k, v in mapping.items()})

    def get(self, key: str) -> CapabilityValue | None:
        return self.items.get(CapabilityKey(key))

    def __len__(self) -> int:
        return len(self.items)

    def keys(self) -> Iterable[CapabilityKey]:
        return self.items.keys()

    def to_json(self) -> dict[str, str | list[str]]:
        """監査記録・表示用の JSON の値(キーの順)。"""
        return {key: self.items[key].to_json() for key in sorted(self.items)}


EMPTY_CAPABILITIES = Capabilities()


# ---------------------------------------------------------------------- 異常の説明


@dataclass(frozen=True)
class FaultDescription:
    """異常の説明。前後の空白を除いて 1〜200 文字、改行・制御文字なし(台帳 E4 の「長さに上限」)。"""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ValidationFailed("description", "文字列でなければならない")
        stripped = self.value.strip()
        if not 1 <= len(stripped) <= MAX_FAULT_DESCRIPTION_LENGTH:
            raise ValidationFailed(
                "description", f"前後の空白を除いて 1〜{MAX_FAULT_DESCRIPTION_LENGTH} 文字でなければならない"
            )
        if has_control_character(stripped):
            raise ValidationFailed("description", "改行・制御文字を含んではならない")
        object.__setattr__(self, "value", stripped)

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------- トークンのハッシュ


@dataclass(frozen=True)
class TokenHash:
    """トークンの SHA-256(16 進 64 文字)。repr・str に値を出さない。"""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _TOKEN_HASH_PATTERN.fullmatch(self.value) is None:
            raise ValidationFailed("token_hash", "SHA-256 の 16 進 64 文字でなければならない")

    def __repr__(self) -> str:
        return "TokenHash(***)"

    def __str__(self) -> str:
        return "***"


# ---------------------------------------------------------------------- 時間の設定


class InvalidTimingPolicy(ValueError):
    """RunnerTimingPolicy の設定エラー(FR-016)。"""


@dataclass(frozen=True)
class RunnerTimingPolicy:
    """生存通知の間隔・offline と判定する時間・リースの長さ(FR-010、FR-015、FR-016)。

    offline_after と lease_duration は、heartbeat_interval の 2 倍より短く設定できない。
    """

    heartbeat_interval: timedelta = timedelta(seconds=30)
    offline_after: timedelta = timedelta(seconds=90)
    lease_duration: timedelta = timedelta(seconds=180)

    def __post_init__(self) -> None:
        for name in ("heartbeat_interval", "offline_after", "lease_duration"):
            value = getattr(self, name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise InvalidTimingPolicy(f"{name} は正の時間でなければならない")
        if self.offline_after < 2 * self.heartbeat_interval:
            raise InvalidTimingPolicy("offline_after は heartbeat_interval の 2 倍より短く設定できない")
        if self.lease_duration < 2 * self.heartbeat_interval:
            raise InvalidTimingPolicy("lease_duration は heartbeat_interval の 2 倍より短く設定できない")
