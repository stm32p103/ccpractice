"""runner コンテキストの拒否(contracts/application-api.md の各ユースケースの「拒否」)。

001 の JobCoreError を基底とし、機械可読の code を持つ。
InvalidDeclaration の violations は「キーと理由」だけを持ち、申告された値は含めない(能力の値や
トークンを例外のメッセージに出さないため)。
"""

from __future__ import annotations

from job_core.job.domain.errors import RunnerMismatch
from job_core.shared.errors import JobCoreError

MAX_VIOLATION_KEY_LENGTH = 64


class RunnerNotFound(JobCoreError):
    code = "runner_not_found"

    def __init__(self, runner_id: str) -> None:
        super().__init__("ランナーが存在しない、または削除済み", runner_id=runner_id)
        self.runner_id = runner_id


class DuplicateRunnerName(JobCoreError):
    code = "duplicate_runner_name"

    def __init__(self, name: str) -> None:
        super().__init__("同じ名前のランナーがある", name=name)
        self.name = name


class RunnerDeleted(JobCoreError):
    code = "runner_deleted"

    def __init__(self, runner_id: str) -> None:
        super().__init__("ランナーは削除済み", runner_id=runner_id)
        self.runner_id = runner_id


class RunnerNotRegistered(JobCoreError):
    code = "runner_not_registered"

    def __init__(self, runner_id: str) -> None:
        super().__init__("ランナーはまだ登録していない", runner_id=runner_id)
        self.runner_id = runner_id


class AlreadyInMaintenance(JobCoreError):
    code = "already_in_maintenance"

    def __init__(self, runner_id: str) -> None:
        super().__init__("既に maintenance である", runner_id=runner_id)
        self.runner_id = runner_id


class NotInMaintenance(JobCoreError):
    code = "not_in_maintenance"

    def __init__(self, runner_id: str) -> None:
        super().__init__("maintenance ではない", runner_id=runner_id)
        self.runner_id = runner_id


class RunnerHasUnfinishedJob(JobCoreError):
    code = "runner_has_unfinished_job"

    def __init__(self, job_id: str) -> None:
        super().__init__("ランナーに未終了のジョブがある", job_id=job_id)
        self.job_id = job_id


class InvalidDeclaration(JobCoreError):
    """能力の申告の拒否。violations は (キー, 理由) の並びで、値は含めない。"""

    code = "invalid_declaration"

    def __init__(self, violations: list[tuple[str, str]]) -> None:
        shortened = tuple((key[:MAX_VIOLATION_KEY_LENGTH], reason) for key, reason in violations)
        super().__init__("能力の申告が許可リストに合わない", violations=[list(v) for v in shortened])
        self.violations = shortened


class InvalidRequirement(JobCoreError):
    """ランナー要件が文法に合わない(判定の対象にしない)。"""

    code = "invalid_requirement"

    def __init__(self, reason: str) -> None:
        super().__init__(reason, reason=reason)
        self.reason = reason


class LeaseExpired(JobCoreError):
    code = "lease_expired"

    def __init__(self, lease_id: str) -> None:
        super().__init__("リースは期限を過ぎている", lease_id=lease_id)
        self.lease_id = lease_id


class InvalidLeaseTransition(JobCoreError):
    code = "invalid_lease_transition"

    def __init__(self, from_status: str, operation: str) -> None:
        super().__init__(
            f"{from_status} のリースに {operation} はできない", from_status=from_status, operation=operation
        )
        self.from_status = from_status
        self.operation = operation


class RunnerAuthenticationFailed(JobCoreError):
    """未知・失効・削除済みのトークン。理由は区別しない。"""

    code = "authentication_failed"

    def __init__(self) -> None:
        super().__init__("認証に失敗した")


class RunnerIdentityMismatch(RunnerMismatch):
    """認証した主体が、操作の対象のランナーと一致しない(別のランナーのトークン。FR-024、US7-4)。

    001 の RunnerMismatch(code = runner_mismatch)の一種として扱い、監査ログに DENIED を残す。
    """

    def __init__(self, runner_id: str) -> None:
        JobCoreError.__init__(self, "認証した主体が、対象のランナーと一致しない", runner_id=runner_id)
        self.job_id = ""
        self.runner_id = runner_id
