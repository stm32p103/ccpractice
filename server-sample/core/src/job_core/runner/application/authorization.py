"""runner の可否の判定(contracts/application-api.md の各ユースケースの必要な権限。research.md R10)。

すべて純粋な関数で、Principal.permissions だけを使う。Principal.kind は参照しない(憲章 原則 9)。
ランナーのトークンで認証した主体は {runner.report, job.execute} だけを持つ(FR-025)。
"""

from __future__ import annotations

from job_core.access.permission import Permission
from job_core.access.principal import Principal
from job_core.job.application.authorization import authorize_view
from job_core.job.domain.errors import PermissionDenied
from job_core.runner.domain.errors import RunnerIdentityMismatch
from job_core.shared.ids import RunnerId

__all__ = [
    "authorize_manage",
    "authorize_report",
    "authorize_request_job",
    "authorize_sweep",
    "authorize_view",
    "require_self",
]


def _require_all(principal: Principal, *permissions: Permission) -> None:
    missing = [p for p in permissions if not principal.has(p)]
    if missing:
        raise PermissionDenied(missing)


def authorize_manage(principal: Principal) -> None:
    """作成・maintenance・異常の手動の解除・削除・トークン・許可リスト。runner.manage。"""
    _require_all(principal, Permission.RUNNER_MANAGE)


def authorize_report(principal: Principal) -> None:
    """登録・生存通知・異常と回復の申告。runner.report。"""
    _require_all(principal, Permission.RUNNER_REPORT)


def authorize_request_job(principal: Principal) -> None:
    """割り当ての要求。runner.report と job.execute の両方。"""
    _require_all(principal, Permission.RUNNER_REPORT, Permission.JOB_EXECUTE)


def authorize_sweep(principal: Principal) -> None:
    """定期処理。runner.sweep。"""
    _require_all(principal, Permission.RUNNER_SWEEP)


def require_self(principal: Principal, runner_id: RunnerId) -> None:
    """認証した主体が対象のランナー自身であること。不一致は RunnerMismatch(FR-024)。"""
    if str(principal.subject_id) != str(runner_id):
        raise RunnerIdentityMismatch(runner_id)
