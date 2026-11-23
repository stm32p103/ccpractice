"""004: ジョブの実行結果の詳細・ログのチャンク・成果物の参照(data-model.md §3)。

用途固有の語を含まない。成果物は参照(UNC パスまたは URL)だけを持ち、中身を持たない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .errors import ValidationFailed

# ランナーが報告できる失敗の理由(固定の語彙。runner-protocol と一致させる)に、コアが付ける lease_expired を加える。
FAILURE_REASONS: frozenset[str] = frozenset(
    {
        "tool_failed",
        "timeout",
        "input_rejected",
        "executor_error",
        "unsupported_job_type",
        "repository_not_allowed",
        "source_unavailable",
        "artifact_limit_exceeded",
        "artifact_store_failed",
        "prepare_timeout",
        "agent_shutdown",
        "agent_restarted",
        "lease_expired",
    }
)
MAX_RUNNER_SUMMARY_CHARS = 200
MAX_ARTIFACTS = 100
MAX_LOG_CHUNK_CHARS = 65536
DEFAULT_LOG_QUOTA_CHARS = 10 * 1024 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_NAME_CHARS = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")


@dataclass(frozen=True)
class ResultCounters:
    """件数と真偽だけ。内容(パス・ログ・値)を持たない。"""

    path_rejections: int = 0
    masked_lines: int = 0
    log_truncated: bool = False

    def __post_init__(self) -> None:
        for name in ("path_rejections", "masked_lines"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationFailed(name, "0 以上の整数でなければならない")
        if not isinstance(self.log_truncated, bool):
            raise ValidationFailed("log_truncated", "真偽でなければならない")


@dataclass(frozen=True)
class ResultDetail:
    exit_code: int | None = None
    failure_reason: str | None = None
    counters: ResultCounters = field(default_factory=ResultCounters)

    def __post_init__(self) -> None:
        if self.exit_code is not None and (isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)):
            raise ValidationFailed("exit_code", "整数でなければならない")
        if self.failure_reason is not None and self.failure_reason not in FAILURE_REASONS:
            raise ValidationFailed("failure_reason", "固定の語彙でない")


class ArtifactKind(StrEnum):
    UNC = "unc"
    URL = "url"


@dataclass(frozen=True)
class JobArtifactRef:
    name: str
    kind: ArtifactKind
    reference: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        bad_name = not isinstance(self.name, str) or not 1 <= len(self.name) <= 255
        if bad_name or any(c in self.name for c in _FORBIDDEN_NAME_CHARS):
            raise ValidationFailed("name", "形式の違反")
        if not isinstance(self.reference, str) or not 1 <= len(self.reference) <= 1024:
            raise ValidationFailed("reference", "長さの違反")
        if self.kind is ArtifactKind.UNC and not self.reference.startswith("\\\\"):
            raise ValidationFailed("reference", "UNC パスでない")
        if self.kind is ArtifactKind.URL and not self.reference.startswith("https://"):
            raise ValidationFailed("reference", "HTTPS の URL でない")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ValidationFailed("size_bytes", "0 以上の整数でなければならない")
        if not isinstance(self.sha256, str) or not _SHA256.match(self.sha256):
            raise ValidationFailed("sha256", "形式の違反")


class LogStream(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"


@dataclass(frozen=True)
class JobLogChunk:
    seq: int
    stream: LogStream
    text: str

    def __post_init__(self) -> None:
        if isinstance(self.seq, bool) or not isinstance(self.seq, int) or self.seq < 0:
            raise ValidationFailed("seq", "0 以上の整数でなければならない")
        if not isinstance(self.text, str) or len(self.text) > MAX_LOG_CHUNK_CHARS:
            raise ValidationFailed("text", "上限を超えている")


@dataclass(frozen=True)
class StoredLogChunk:
    seq: int
    stream: LogStream
    text: str
    received_at: datetime
