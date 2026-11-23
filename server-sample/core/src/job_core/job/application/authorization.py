"""可否の判定(contracts/application-api.md「可否の表」、research.md R8)。

すべて純粋な関数で、Principal.permissions だけを使う。Principal.kind は参照しない(憲章 原則 9)。
拒否は PermissionDenied(required=不足している権限、または候補の一覧)。
"""

from __future__ import annotations

from job_core.access.permission import Permission
from job_core.access.principal import Principal
from job_core.job.domain.errors import PermissionDenied
from job_core.job.domain.states import JobState
from job_core.shared.ids import SubjectId


def _require_all(principal: Principal, *permissions: Permission) -> None:
    missing = [p for p in permissions if not principal.has(p)]
    if missing:
        raise PermissionDenied(missing)


def _require_any(principal: Principal, *permissions: Permission) -> None:
    if not any(principal.has(p) for p in permissions):
        raise PermissionDenied(permissions)


def authorize_submit(principal: Principal, *, owner: SubjectId, placed: bool) -> None:
    """提出。自分の名義は JOB_SUBMIT、他人の名義は SUBMIT_ON_BEHALF。位置の指定には QUEUE_SCHEDULE も要る。"""
    base = Permission.JOB_SUBMIT if owner == principal.subject_id else Permission.SUBMIT_ON_BEHALF
    if placed:
        _require_all(principal, base, Permission.QUEUE_SCHEDULE)
    else:
        _require_all(principal, base)


def authorize_retry(principal: Principal, *, placed: bool) -> None:
    """やり直し。誰のジョブでも JOB_SUBMIT。位置の指定には QUEUE_SCHEDULE も要る。"""
    if placed:
        _require_all(principal, Permission.JOB_SUBMIT, Permission.QUEUE_SCHEDULE)
    else:
        _require_all(principal, Permission.JOB_SUBMIT)


def authorize_reschedule(principal: Principal) -> None:
    """スケジュール変更。誰のジョブでも QUEUE_SCHEDULE。"""
    _require_all(principal, Permission.QUEUE_SCHEDULE)


def authorize_cancel(principal: Principal, *, owner: SubjectId, state: JobState) -> None:
    """中断。その時点の状態と所有で判定する。

    自分のジョブは GENERAL。他人の待機中は CANCEL_QUEUED、他人の実行中は FORCE_ABORT。
    他人の終了済みのジョブは、どちらかの権限があれば判定を通し、状態の規則(InvalidStateTransition)で拒否される。
    """
    if owner == principal.subject_id:
        _require_all(principal, Permission.GENERAL)
    elif state is JobState.QUEUED:
        _require_all(principal, Permission.CANCEL_QUEUED)
    elif state is JobState.RUNNING:
        _require_all(principal, Permission.FORCE_ABORT)
    else:
        _require_any(principal, Permission.CANCEL_QUEUED, Permission.FORCE_ABORT)


def authorize_view(principal: Principal) -> None:
    """一覧・詳細・操作の経緯の閲覧。GENERAL。"""
    _require_all(principal, Permission.GENERAL)


def authorize_read_output(principal: Principal) -> None:
    """ログ・成果物の参照の閲覧(004)。JOB_READ_OUTPUT。"""
    _require_all(principal, Permission.JOB_READ_OUTPUT)


def authorize_audit_read_all(principal: Principal) -> None:
    """監査ログ全体の閲覧。AUDIT_READ_ALL。"""
    _require_all(principal, Permission.AUDIT_READ_ALL)


def authorize_execute(principal: Principal) -> None:
    """割り当ての取得・終了の報告・停止の確認。JOB_EXECUTE。"""
    _require_all(principal, Permission.JOB_EXECUTE)


def authorize_purge(principal: Principal) -> None:
    """保持期間による削除の実行。RETENTION_PURGE。"""
    _require_all(principal, Permission.RETENTION_PURGE)
