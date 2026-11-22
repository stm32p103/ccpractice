"""ジョブの検索の頁送りの cursor(003 research.md R8)。

直前の頁の最後の (submitted_at, job_id) を表す不透明な値。キーは不変なので、頁の途中で状態の変化・削除があっても
続きに重複も欠落も起きない。
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime

from job_core.job.domain.errors import ValidationFailed
from job_core.shared.ids import JobId


def encode_search_cursor(submitted_at: datetime, job_id: JobId) -> str:
    payload = json.dumps([submitted_at.astimezone(UTC).isoformat(), job_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_search_cursor(cursor: str) -> tuple[datetime, JobId]:
    """不正な cursor は ValidationFailed("cursor", ...)。"""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        at_text, job_id = decoded
        at = datetime.fromisoformat(at_text)
        if not isinstance(job_id, str) or not job_id or at.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise ValidationFailed("cursor", "不正な cursor") from None
    return at, JobId(job_id)
