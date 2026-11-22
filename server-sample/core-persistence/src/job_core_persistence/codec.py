"""集約・値オブジェクト(データクラス)と JSON の相互変換。

保存する文書(JSONB)は、データクラスの項目を、型の注釈にそって JSON にしたもの。データクラスには `@`(クラス名)を付ける
(和集合の型の復元用)。列挙は値、日時は ISO 8601(タイムゾーン必須)、時間は整数のマイクロ秒、集合は整列した配列にする。
`_events` のような、集約が持つ未確定の内部の状態は保存しない。
"""

from __future__ import annotations

import dataclasses
import types
import typing
from datetime import datetime, timedelta
from enum import Enum
from functools import cache
from typing import Any, Union, get_args, get_origin

SKIPPED_FIELDS = frozenset({"_events"})
TAG = "@"


@cache
def _hints(cls: type) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def encode(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("日時はタイムゾーン付きでなければならない")
        return value.isoformat()
    if isinstance(value, timedelta):
        return value // timedelta(microseconds=1)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        body: dict[str, Any] = {TAG: type(value).__name__}
        for f in dataclasses.fields(value):
            if f.name not in SKIPPED_FIELDS:
                body[f.name] = encode(getattr(value, f.name))
        return body
    if isinstance(value, set | frozenset):
        return sorted((encode(v) for v in value), key=lambda v: (str(type(v)), str(v)))
    if isinstance(value, list | tuple):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    raise TypeError(f"保存できない型: {type(value).__name__}")


def _is_union(hint: Any) -> bool:
    return get_origin(hint) in (Union, types.UnionType)


def decode(hint: Any, data: Any) -> Any:
    if data is None:
        return None
    if hint is Any or hint is None:
        return data
    supertype = getattr(hint, "__supertype__", None)
    if supertype is not None:  # NewType
        return decode(supertype, data)
    if _is_union(hint):
        candidates = [a for a in get_args(hint) if a is not type(None)]
        if len(candidates) == 1:
            return decode(candidates[0], data)
        if isinstance(data, dict) and TAG in data:
            for candidate in candidates:
                if isinstance(candidate, type) and candidate.__name__ == data[TAG]:
                    return decode(candidate, data)
        for candidate in candidates:
            if isinstance(candidate, type) and isinstance(data, candidate):
                return data
        raise ValueError("和集合の型を復元できない")
    origin = get_origin(hint)
    if origin in (list, tuple, set, frozenset):
        args = get_args(hint)
        item = args[0] if args else Any
        items = [decode(item, v) for v in data]
        return origin(items) if origin is not tuple else tuple(items)
    if origin in (dict, typing.Mapping) or (origin is not None and getattr(origin, "__name__", "") == "Mapping"):
        key_hint, value_hint = get_args(hint) or (Any, Any)
        return {decode(key_hint, k): decode(value_hint, v) for k, v in data.items()}
    if isinstance(hint, type):
        if issubclass(hint, Enum):
            return hint(data)
        if issubclass(hint, datetime):
            return datetime.fromisoformat(data)
        if issubclass(hint, timedelta):
            return timedelta(microseconds=data)
        if dataclasses.is_dataclass(hint):
            hints = _hints(hint)
            kwargs = {
                f.name: decode(hints[f.name], data[f.name])
                for f in dataclasses.fields(hint)
                if f.init and f.name not in SKIPPED_FIELDS and f.name in data
            }
            return hint(**kwargs)
        if hint in (str, int, float, bool):
            return data
    return data
