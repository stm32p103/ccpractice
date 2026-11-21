"""ジョブの状態(data-model.md「JobState と遷移表」)。値は直列化の形(小文字)。"""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATES


TERMINAL_STATES: frozenset[JobState] = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED})
