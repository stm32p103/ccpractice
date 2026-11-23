"""ランナープロトコルの固定の語彙(contracts/runner-protocol.schema.json)。"""

from __future__ import annotations

from enum import StrEnum

PROTOCOL_VERSION = "1.1"


class FailureReason(StrEnum):
    TOOL_FAILED = "tool_failed"
    TIMEOUT = "timeout"
    INPUT_REJECTED = "input_rejected"
    EXECUTOR_ERROR = "executor_error"
    UNSUPPORTED_JOB_TYPE = "unsupported_job_type"
    REPOSITORY_NOT_ALLOWED = "repository_not_allowed"
    SOURCE_UNAVAILABLE = "source_unavailable"
    ARTIFACT_LIMIT_EXCEEDED = "artifact_limit_exceeded"
    ARTIFACT_STORE_FAILED = "artifact_store_failed"
    PREPARE_TIMEOUT = "prepare_timeout"
    AGENT_SHUTDOWN = "agent_shutdown"
    AGENT_RESTARTED = "agent_restarted"


class Stream(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"


class ArtifactKind(StrEnum):
    UNC = "unc"
    URL = "url"


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


MAX_LOG_CHUNK_CHARS = 65536
MAX_RESULT_SUMMARY_CHARS = 200
MAX_ARTIFACTS = 100
