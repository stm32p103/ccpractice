"""runner の監査記録の組み立てと、拒否の記録(research.md R14。FR-028)。

- 成功した操作は、本体と同じ UoW の AuditLog.append に残す(本体と一緒に確定する)。
- 拒否(権限・ランナーの不一致・認証・申告の検査)は、本体の変更がないため、別の UoW の append_denied に残す。
- トークンの値・ハッシュ・申告された能力の値を、どの記録にも入れない。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application.ports import AuditLog
from job_core.job.domain.audit import AuditOperation, AuditOutcome, AuditRecord, Denial
from job_core.job.domain.errors import PermissionDenied, RunnerMismatch
from job_core.runner.application.ports import RunnerDependencies
from job_core.runner.domain.errors import InvalidDeclaration
from job_core.runner.domain.runner import Connectivity, Runner
from job_core.shared.ids import JobId, RunnerId, SubjectId

ANONYMOUS = SubjectId("unauthenticated")


def make_runner_record(
    deps: RunnerDependencies,
    principal: Principal,
    operation: AuditOperation,
    runner_id: RunnerId | None,
    *,
    job_id: JobId | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> AuditRecord:
    return AuditRecord(
        record_id=deps.ids.new_id(),
        occurred_at=deps.clock.now(),
        actor=principal.subject_id,
        actor_kind=principal.kind,
        operation=operation,
        job_id=job_id,
        outcome=AuditOutcome.SUCCEEDED,
        before=before or {},
        after=after or {},
        reason=reason,
        runner_id=runner_id,
    )


def record_denial(
    deps: RunnerDependencies,
    *,
    actor: SubjectId,
    actor_kind: PrincipalKind,
    operation: AuditOperation,
    runner_id: RunnerId | None,
    code: str,
    required: tuple[str, ...] = (),
    attempted: Mapping[str, Any] | None = None,
) -> None:
    """拒否を、別の UoW で記録する(呼び出し時点で独立に確定する)。"""
    record = AuditRecord(
        record_id=deps.ids.new_id(),
        occurred_at=deps.clock.now(),
        actor=actor,
        actor_kind=actor_kind,
        operation=operation,
        job_id=None,
        outcome=AuditOutcome.DENIED,
        after=attempted or {},
        denial=Denial(code=code, required=required),
        runner_id=runner_id,
    )
    with deps.uow_factory() as uow:
        uow.audit.append_denied(record)


def audited[T](
    deps: RunnerDependencies,
    principal: Principal,
    operation: AuditOperation,
    runner_id: RunnerId | None,
    action: Callable[[], T],
    *,
    attempted: Mapping[str, Any] | None = None,
) -> T:
    """action を実行し、権限・ランナーの不一致・申告の検査による拒否なら、記録してから送出し直す。"""
    try:
        return action()
    except (PermissionDenied, RunnerMismatch) as error:
        required = error.required if isinstance(error, PermissionDenied) else ()
        record_denial(
            deps,
            actor=principal.subject_id,
            actor_kind=principal.kind,
            operation=operation,
            runner_id=runner_id,
            code=error.code,
            required=tuple(required),
            attempted=attempted,
        )
        raise
    except InvalidDeclaration as error:
        # 能力の値は記録しない(キーと理由だけ)
        record_denial(
            deps,
            actor=principal.subject_id,
            actor_kind=principal.kind,
            operation=operation,
            runner_id=runner_id,
            code=error.code,
            attempted={"violations": [list(v) for v in error.violations]},
        )
        raise


def append_connectivity_change(
    deps: RunnerDependencies, audit_log: AuditLog, principal: Principal, runner: Runner, *, now: datetime
) -> bool:
    """接続の状態(生存通知の有無で決まる online / offline)が、記録上の状態から変わっていれば、監査に残す。

    変化があれば RUNNER_ONLINE / RUNNER_OFFLINE を追記して真を返す。runner の recorded_connectivity も更新する。
    """
    before = runner.recorded_connectivity
    current = runner.connectivity_at(now, deps.timing)
    if not runner.mark_connectivity(current):
        return False
    operation = AuditOperation.RUNNER_ONLINE if current is Connectivity.ONLINE else AuditOperation.RUNNER_OFFLINE
    audit_log.append(
        make_runner_record(
            deps,
            principal,
            operation,
            runner.runner_id,
            before={"connectivity": before.value},
            after={
                "connectivity": current.value,
                "last_seen_at": runner.last_seen_at.isoformat() if runner.last_seen_at else None,
            },
        )
    )
    return True
