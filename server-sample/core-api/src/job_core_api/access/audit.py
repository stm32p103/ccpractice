"""API の層の監査(research.md R10)。

認証の失敗(AUTH_FAILED。actor は `unauthenticated`、actor_kind は ANONYMOUS)と、同じ接続元・同じ種類の失敗の
窓による抑制。窓の最初の 1 件を記録し、窓の中の残りは数えて、窓が閉じたとき件数つきの 1 件を追記する
(監査ログは追記専用なので更新しない)。認証情報の値・ハッシュは記録しない(T-A1)。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application.ports import CoreDependencies
from job_core.job.domain.audit import AuditOperation, AuditOutcome, AuditRecord, Denial
from job_core.shared.ids import SubjectId

from ..settings import ApiSettings

UNAUTHENTICATED = SubjectId("unauthenticated")
AUTHENTICATION_FAILED = "authentication_failed"


def make_audit_record(
    deps: CoreDependencies,
    principal: Principal,
    operation: AuditOperation,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditRecord:
    """API の層の操作(成功)の監査記録。job_id は持たない。"""
    return AuditRecord(
        record_id=deps.ids.new_id(),
        occurred_at=deps.clock.now(),
        actor=principal.subject_id,
        actor_kind=principal.kind,
        operation=operation,
        job_id=None,
        outcome=AuditOutcome.SUCCEEDED,
        before=before or {},
        after=after or {},
        reason=reason,
    )


def append_success(deps: CoreDependencies, record: AuditRecord) -> None:
    """成功の記録を、独立した UoW で確定する。"""
    with deps.uow_factory() as uow:
        uow.audit.append(record)
        uow.commit()


def record_permission_denied(
    deps: CoreDependencies,
    principal: Principal,
    operation: AuditOperation,
    required: tuple[str, ...],
    attempted: dict[str, Any] | None = None,
) -> None:
    """API の層で判定した権限の拒否を記録する(コアの拒否と同じ形)。"""
    record = AuditRecord(
        record_id=deps.ids.new_id(),
        occurred_at=deps.clock.now(),
        actor=principal.subject_id,
        actor_kind=principal.kind,
        operation=operation,
        job_id=None,
        outcome=AuditOutcome.DENIED,
        after=attempted or {},
        denial=Denial(code="permission_denied", required=required),
    )
    with deps.uow_factory() as uow:
        uow.audit.append_denied(record)


@dataclass
class _Window:
    started_at: datetime
    suppressed: int = 0


class AuthFailureAuditor:
    """認証の失敗を、窓で抑制して監査ログに記録する。"""

    def __init__(self, deps: CoreDependencies, settings: ApiSettings) -> None:
        self._deps = deps
        self._window = settings.auth_failure_window
        self._windows: dict[tuple[str, str], _Window] = {}
        self._lock = threading.Lock()

    def record(self, source: str, kind: str) -> None:
        """認証の失敗を 1 件申告する。kind は失敗の種類(`session`、`service`、`runner`、`login`、`malformed`)。"""
        now = self._deps.clock.now()
        key = (source, kind)
        pending: list[AuditRecord] = []
        with self._lock:
            window = self._windows.get(key)
            if window is not None and now >= window.started_at + self._window:
                if window.suppressed:
                    pending.append(self._record(now, source, kind, suppressed=window.suppressed))
                del self._windows[key]
                window = None
            if window is None:
                self._windows[key] = _Window(started_at=now)
                pending.append(self._record(now, source, kind))
            else:
                window.suppressed += 1
        self._append(pending)

    def flush(self) -> int:
        """閉じた窓の件数つきの記録を追記する(定期処理から呼ぶ)。追記した件数を返す。"""
        now = self._deps.clock.now()
        pending: list[AuditRecord] = []
        with self._lock:
            for key, window in list(self._windows.items()):
                if now >= window.started_at + self._window:
                    if window.suppressed:
                        pending.append(self._record(now, key[0], key[1], suppressed=window.suppressed))
                    del self._windows[key]
        self._append(pending)
        return len(pending)

    def _record(self, now: datetime, source: str, kind: str, suppressed: int | None = None) -> AuditRecord:
        after: dict[str, Any] = {"source": source, "kind": kind}
        if suppressed is not None:
            after["suppressed"] = suppressed
        return AuditRecord(
            record_id=self._deps.ids.new_id(),
            occurred_at=now,
            actor=UNAUTHENTICATED,
            actor_kind=PrincipalKind.ANONYMOUS,
            operation=AuditOperation.AUTH_FAILED,
            job_id=None,
            outcome=AuditOutcome.DENIED,
            after=after,
            denial=Denial(code=AUTHENTICATION_FAILED),
        )

    def _append(self, records: list[AuditRecord]) -> None:
        for record in records:
            with self._deps.uow_factory() as uow:
                uow.audit.append_denied(record)
