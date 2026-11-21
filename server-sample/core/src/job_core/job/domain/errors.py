"""job コンテキストの拒否(contracts/application-api.md「拒否の一覧」)。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from job_core.shared.errors import JobCoreError


class ValidationFailed(JobCoreError):
    code = "validation_failed"

    def __init__(self, field: str, detail: str) -> None:
        super().__init__(f"{field}: {detail}", field=field, detail=detail)
        self.field = field
        self.detail = detail


class NoEligibleRunner(JobCoreError):
    code = "no_eligible_runner"

    def __init__(self) -> None:
        super().__init__("要件を満たしうるランナーが登録されていない")


class DuplicateQueuedJob(JobCoreError):
    code = "duplicate_queued_job"

    def __init__(self, existing_job_id: str) -> None:
        super().__init__("同じ内容のジョブが待機中", existing_job_id=existing_job_id)
        self.existing_job_id = existing_job_id


class PermissionDenied(JobCoreError):
    code = "permission_denied"

    def __init__(self, required: Iterable[str]) -> None:
        required_tuple = tuple(str(p) for p in required)
        super().__init__("権限がない", required=list(required_tuple))
        self.required = required_tuple


class JobNotFound(JobCoreError):
    code = "job_not_found"

    def __init__(self, job_id: str) -> None:
        super().__init__("ジョブが存在しない", job_id=job_id)
        self.job_id = job_id


class TargetNotQueued(JobCoreError):
    code = "target_not_queued"

    def __init__(self, job_id: str, state: str | None = None) -> None:
        super().__init__("対象のジョブが待機中でない", job_id=job_id, state=state)
        self.job_id = job_id
        self.state = state


class AnchorNotQueued(JobCoreError):
    code = "anchor_not_queued"

    def __init__(self, anchor_job_id: str) -> None:
        super().__init__("基準のジョブが待機中でない", anchor_job_id=anchor_job_id)
        self.anchor_job_id = anchor_job_id


class SelfAnchor(JobCoreError):
    code = "self_anchor"

    def __init__(self) -> None:
        super().__init__("自分自身を基準にした移動はできない")


class InvalidStateTransition(JobCoreError):
    code = "invalid_state_transition"

    def __init__(self, from_state: str, operation: str) -> None:
        super().__init__(f"{from_state} から {operation} はできない", from_state=from_state, operation=operation)
        self.from_state = from_state
        self.operation = operation


class ReasonRequired(JobCoreError):
    code = "reason_required"

    def __init__(self) -> None:
        super().__init__("実行中のジョブの強制中断には理由が必要")


class AbortAlreadyRequested(JobCoreError):
    code = "abort_already_requested"

    def __init__(self, requested_at: datetime) -> None:
        super().__init__("中断の要求が既にある", requested_at=requested_at.isoformat())
        self.requested_at = requested_at


class RunnerBusy(JobCoreError):
    code = "runner_busy"

    def __init__(self, job_id: str) -> None:
        super().__init__("ランナーに未終了のジョブがある", job_id=job_id)
        self.job_id = job_id


class RunnerMismatch(JobCoreError):
    code = "runner_mismatch"

    def __init__(self, job_id: str) -> None:
        super().__init__("報告したランナーがジョブの割り当て先でない", job_id=job_id)
        self.job_id = job_id


class ConcurrencyConflict(JobCoreError):
    code = "concurrency_conflict"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or "同時の更新と衝突した")
