"""メッセージの検査(送信前・受信後)。スキーマの正本は runner-protocol/schemas/。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .messages import (
    FinishReport,
    HeartbeatResult,
    LogChunk,
    LogChunkResult,
    ProtocolViolation,
    SourceCredential,
)

_PARSERS: dict[str, Callable[[Mapping[str, Any]], Any]] = {
    "LogChunk": LogChunk.from_json,
    "LogChunkResult": LogChunkResult.from_json,
    "FinishReport": FinishReport.from_json,
    "HeartbeatResult": HeartbeatResult.from_json,
    "SourceCredential": SourceCredential.from_json,
}


def parse(name: str, data: Mapping[str, Any]) -> Any:
    """name のメッセージとして検査し、値オブジェクトを返す。違反は ProtocolViolation(入力の値を含めない)。"""
    try:
        parser = _PARSERS[name]
    except KeyError as exc:
        raise ProtocolViolation(name, "未知のメッセージ") from exc
    return parser(data)


def check_outgoing(name: str, data: Mapping[str, Any]) -> None:
    """送信前の検査。違反なら送らない。"""
    parse(name, data)
