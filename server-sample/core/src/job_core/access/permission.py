"""権限(contracts/application-api.md「権限」)。

JOB_SUBMIT 〜 SUBMIT_ON_BEHALF の 7 種は 001 spec FR-023 の権限、JOB_EXECUTE と RETENTION_PURGE は
001 plan で追加した権限(001 research.md R8)。RUNNER_MANAGE・RUNNER_REPORT・RUNNER_SWEEP は
002 の権限(002 research.md R10)。可否は権限だけで判定する(憲章 原則 9)。
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    JOB_SUBMIT = "job.submit"
    GENERAL = "job.general"
    QUEUE_SCHEDULE = "queue.schedule"
    CANCEL_QUEUED = "job.cancel_queued"
    FORCE_ABORT = "job.force_abort"
    AUDIT_READ_ALL = "audit.read_all"
    SUBMIT_ON_BEHALF = "job.submit_on_behalf"
    JOB_EXECUTE = "job.execute"
    RETENTION_PURGE = "retention.purge"
    RUNNER_MANAGE = "runner.manage"
    RUNNER_REPORT = "runner.report"
    RUNNER_SWEEP = "runner.sweep"
