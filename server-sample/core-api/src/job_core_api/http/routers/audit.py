"""監査ログのルーター(contracts/http-api.md §2.4。001)。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from job_core.job.application import AuditOperation, AuditOutcome

from ..authn import CurrentPrincipal, Deps
from ..schemas_audit import AuditLogPageOut
from ..schemas_jobs import RfcDatetime

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=AuditLogPageOut, operation_id="get_audit_log")
def get_audit_log(
    principal: CurrentPrincipal,
    deps: Deps,
    since: RfcDatetime | None = None,
    until: RfcDatetime | None = None,
    job_id: str | None = None,
    actor: str | None = None,
    operation: AuditOperation | None = None,
    outcome: AuditOutcome | None = None,
    runner_id: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditLogPageOut:
    """監査ログ全体(拒否を含む)。`audit.read_all` を要する。"""
    page = deps.core.get_audit_log(
        principal,
        since=since,
        until=until,
        job_id=job_id,
        actor=actor,
        operation=operation,
        outcome=outcome,
        runner_id=runner_id,
        cursor=cursor,
        limit=limit,
    )
    return AuditLogPageOut.of(page)
