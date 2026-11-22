"""待機列のルーター(contracts/http-api.md §2.2)。全員が閲覧できる(`job.general`。001 FR-022)。"""

from __future__ import annotations

from fastapi import APIRouter

from ..authn import CurrentPrincipal, Deps
from ..schemas_jobs import QueueOut

router = APIRouter(prefix="/queue", tags=["jobs"])


@router.get("", response_model=QueueOut, operation_id="get_queue")
def get_queue(principal: CurrentPrincipal, deps: Deps) -> QueueOut:
    """待機中の全件を、待機列の順序で返す。"""
    return QueueOut.of(deps.core.list_jobs(principal, states=["queued"]).queued)
