"""ジョブのルーター(contracts/http-api.md §2.2)。

コアのユースケースに Principal を渡すだけで、権限・規則の判定を重複して持たない(research.md R6)。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from job_core.job.domain.states import JobState

from ..authn import CurrentPrincipal, Deps
from ..schemas_audit import AuditRecordOut
from ..schemas_jobs import (
    CancelRequest,
    CancelResultOut,
    JobDetail,
    JobPage,
    RescheduleRequest,
    RescheduleResultOut,
    RetryRequest,
    RfcDatetime,
    SubmitRequest,
    SubmitResultOut,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=201, response_model=SubmitResultOut, operation_id="submit_job")
def submit_job(body: SubmitRequest, response: Response, principal: CurrentPrincipal, deps: Deps) -> SubmitResultOut:
    """ジョブを提出する。`on_behalf_of` と `placement` は、それぞれ提出代行・スケジュールの権限を要する。"""
    definition = body.definition
    result = deps.core.submit(
        principal,
        job_type=definition.job_type,
        requirement=definition.requirement,
        payload=definition.payload,
        timeout=definition.timeout(),
        source=definition.source,
        revision=definition.revision,
        on_behalf_of=body.on_behalf_of,
        placement=body.placement.to_core() if body.placement else None,
    )
    response.headers["Location"] = f"/v1/jobs/{result.job_id}"
    deps.publisher.job_submitted(result.job_id)
    return SubmitResultOut.of(result)


@router.get("", response_model=JobPage, operation_id="list_jobs")
def list_jobs(
    principal: CurrentPrincipal,
    deps: Deps,
    state: Annotated[list[JobState] | None, Query(description="状態(複数指定できる)")] = None,
    submitter: Annotated[str | None, Query(description="提出者(名義上の提出者)")] = None,
    submitted_from: Annotated[RfcDatetime | None, Query(description="提出日時の下限(含む)")] = None,
    submitted_to: Annotated[RfcDatetime | None, Query(description="提出日時の上限(含まない)")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JobPage:
    """履歴の検索。提出日時の新しい順。payload を含まない。"""
    page = deps.core.search_jobs(
        principal,
        states=state,
        owner=submitter,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        cursor=cursor,
        limit=limit,
    )
    return JobPage.of(page)


@router.get("/{job_id}", response_model=JobDetail, operation_id="get_job")
def get_job(job_id: str, principal: CurrentPrincipal, deps: Deps) -> JobDetail:
    """ジョブの詳細(定義を含む)。"""
    return JobDetail.of(deps.core.get_job(principal, job_id=job_id))


@router.get("/{job_id}/history", response_model=list[AuditRecordOut], operation_id="get_job_history")
def get_job_history(job_id: str, principal: CurrentPrincipal, deps: Deps) -> list[AuditRecordOut]:
    """ジョブの操作の経緯(成功した操作)。"""
    return [AuditRecordOut.of(record) for record in deps.core.get_job_history(principal, job_id=job_id)]


@router.post("/{job_id}/reschedule", response_model=RescheduleResultOut, operation_id="reschedule_job")
def reschedule_job(
    job_id: str, body: RescheduleRequest, principal: CurrentPrincipal, deps: Deps
) -> RescheduleResultOut:
    """待機中のジョブの位置を変える(スケジュール変更)。"""
    result = deps.core.reschedule(principal, job_id=job_id, placement=body.placement.to_core())
    deps.publisher.job_rescheduled(result.job_id)
    return RescheduleResultOut.of(result)


@router.post("/{job_id}/cancel", response_model=CancelResultOut, operation_id="cancel_job")
def cancel_job(job_id: str, body: CancelRequest, principal: CurrentPrincipal, deps: Deps) -> CancelResultOut:
    """取り消し(待機中)または強制中断の要求(実行中。理由が必須)。"""
    result = deps.core.cancel(principal, job_id=job_id, reason=body.reason)
    deps.publisher.job_cancelled(result)
    return CancelResultOut.of(result)


@router.post("/{job_id}/retry", status_code=201, response_model=SubmitResultOut, operation_id="retry_job")
def retry_job(
    job_id: str, body: RetryRequest, response: Response, principal: CurrentPrincipal, deps: Deps
) -> SubmitResultOut:
    """終了済みのジョブを、新しいジョブとしてやり直す。"""
    placement = body.placement.to_core() if body.placement else None
    result = deps.core.retry(principal, job_id=job_id, placement=placement)
    response.headers["Location"] = f"/v1/jobs/{result.job_id}"
    deps.publisher.job_retried(result.job_id)
    return SubmitResultOut.of(result)
