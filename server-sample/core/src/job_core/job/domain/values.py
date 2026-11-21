"""job コンテキストの値オブジェクト(data-model.md §1)。

各値の制約は data-model.md を正とする。違反は ValidationFailed(field, detail)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any

from job_core.shared.ids import JobId, is_valid_id

from .errors import ValidationFailed

JsonValue = Any
"""JSON で表せる値(dict / list / str / 数値 / bool / None)。"""


def _canonical_json(value: object, field_name: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(field_name, "JSON で表せる値でなければならない") from exc


@dataclass(frozen=True)
class JobType:
    """ジョブの種類(data-model.md JobType)。前後の空白を除いて保持する。"""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ValidationFailed("job_type", "文字列でなければならない")
        stripped = self.value.strip()
        if not 1 <= len(stripped) <= 128:
            raise ValidationFailed("job_type", "前後の空白を除いて 1〜128 文字でなければならない")
        object.__setattr__(self, "value", stripped)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class _OpaqueJson:
    """中身を解釈しない JSON の値。正規化した JSON の文字列として不変に保持する。"""

    _json: str = field(repr=False)

    @property
    def value(self) -> JsonValue:
        """保持している値の新しい複製を返す(呼び出し側が変更しても、保持している値は変わらない)。"""
        return json.loads(self._json)

    @property
    def canonical_json(self) -> str:
        return self._json


class RunnerRequirement(_OpaqueJson):
    """ランナー要件(data-model.md RunnerRequirement)。001 は中身を解釈せず、判定は RunnerEligibility に任せる。"""

    @classmethod
    def of(cls, value: JsonValue) -> RunnerRequirement:
        if value is None:
            raise ValidationFailed("requirement", "必須")
        return cls(_canonical_json(value, "requirement"))


class Payload(_OpaqueJson):
    """payload(data-model.md Payload)。中身は検査しない(FR-001)。深い複製として不変に保持する。"""

    @classmethod
    def of(cls, value: JsonValue) -> Payload:
        if value is None:
            raise ValidationFailed("payload", "必須")
        return cls(_canonical_json(value, "payload"))


@dataclass(frozen=True)
class Timeout:
    """タイムアウト(data-model.md Timeout)。正の値。"""

    value: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.value, timedelta):
            raise ValidationFailed("timeout", "時間の長さでなければならない")
        if self.value <= timedelta(0):
            raise ValidationFailed("timeout", "正の値でなければならない")


@dataclass(frozen=True)
class SourceRef:
    """出所情報(data-model.md SourceRef.source、SourceRef.revision)。形式は検査しない。"""

    source: str
    revision: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not 1 <= len(self.source) <= 512:
            raise ValidationFailed("source_ref.source", "1〜512 文字の文字列でなければならない")
        if self.revision is not None and (not isinstance(self.revision, str) or not 1 <= len(self.revision) <= 256):
            raise ValidationFailed("source_ref.revision", "1〜256 文字の文字列でなければならない")


@dataclass(frozen=True)
class ResultSummary:
    """結果の要約(data-model.md ResultSummary)。超えた場合は切り詰めず拒否する。"""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or len(self.value) > 1024:
            raise ValidationFailed("result_summary", "1024 文字以内の文字列でなければならない")


@dataclass(frozen=True)
class Reason:
    """中断の理由など(data-model.md Reason)。前後の空白を除いて保持する。"""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ValidationFailed("reason", "文字列でなければならない")
        stripped = self.value.strip()
        if not 1 <= len(stripped) <= 1000:
            raise ValidationFailed("reason", "前後の空白を除いて 1〜1000 文字でなければならない")
        object.__setattr__(self, "value", stripped)


class PlacementSide(StrEnum):
    BEFORE = "before"
    AFTER = "after"


@dataclass(frozen=True)
class Placement:
    """位置の指定(data-model.md Placement.anchor、Placement.side)。"""

    anchor: JobId
    side: PlacementSide

    def __post_init__(self) -> None:
        if not is_valid_id(self.anchor):
            raise ValidationFailed("placement.anchor", "空でない識別子でなければならない")
        try:
            object.__setattr__(self, "side", PlacementSide(self.side))
        except ValueError as exc:
            raise ValidationFailed("placement.side", "before または after でなければならない") from exc

    @classmethod
    def before(cls, anchor: str) -> Placement:
        return cls(JobId(anchor), PlacementSide.BEFORE)

    @classmethod
    def after(cls, anchor: str) -> Placement:
        return cls(JobId(anchor), PlacementSide.AFTER)


@dataclass(frozen=True)
class DuplicateKey:
    """重複の判定の鍵(data-model.md DuplicateKey)。出所・リビジョン・ジョブの種類。"""

    source: str
    revision: str | None
    job_type: str
