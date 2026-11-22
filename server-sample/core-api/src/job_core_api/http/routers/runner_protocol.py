"""ランナー向けのルーター(contracts/http-api.md §2.6。research.md R16)。最小の範囲(004 が拡張する)。

ランナーの識別子は URL に含めない。認証した主体(`rt_` のトークン)の識別子を、002 のユースケースの
`runner_id` として渡す(他のランナーを対象にできない。FR-011、T-A4)。権限の判定はコアが行う
(人間・サービスの主体は `runner.report` を持たないため `permission_denied`)。
"""

from __future__ import annotations

from fastapi import APIRouter

from ...events.ports import ChangeKind
from ..authn import CurrentPrincipal, Deps
from ..schemas_runner_protocol import (
    FaultRequest,
    FinishRequest,
    FinishResultOut,
    HeartbeatResultOut,
    JobRequestResultOut,
    RegisterRequest,
)

router = APIRouter(prefix="/runner", tags=["runner"])


@router.post("/registration", response_model=HeartbeatResultOut, operation_id="runner_register")
def register(body: RegisterRequest, principal: CurrentPrincipal, deps: Deps) -> HeartbeatResultOut:
    """起動時の登録(能力の申告)。"""
    result = deps.core.register_runner(principal, runner_id=principal.subject_id, capabilities=body.capabilities)
    deps.publisher.runner_event(principal.subject_id, ChangeKind.REGISTERED)
    return HeartbeatResultOut.of(result)


@router.post("/heartbeat", response_model=HeartbeatResultOut, operation_id="runner_heartbeat")
def heartbeat(principal: CurrentPrincipal, deps: Deps) -> HeartbeatResultOut:
    """生存通知(リースの延長)。"""
    result = deps.core.heartbeat(principal, runner_id=principal.subject_id)
    deps.publisher.runner_event(principal.subject_id)
    return HeartbeatResultOut.of(result)


@router.post("/fault", response_model=HeartbeatResultOut, operation_id="runner_report_fault")
def report_fault(body: FaultRequest, principal: CurrentPrincipal, deps: Deps) -> HeartbeatResultOut:
    """異常の申告。"""
    result = deps.core.report_fault(principal, runner_id=principal.subject_id, description=body.description)
    deps.publisher.runner_event(principal.subject_id, ChangeKind.FAULT_CHANGED)
    return HeartbeatResultOut.of(result)


@router.delete("/fault", response_model=HeartbeatResultOut, operation_id="runner_report_recovered")
def report_recovered(principal: CurrentPrincipal, deps: Deps) -> HeartbeatResultOut:
    """異常からの回復の申告。"""
    result = deps.core.report_recovered(principal, runner_id=principal.subject_id)
    deps.publisher.runner_event(principal.subject_id, ChangeKind.FAULT_CHANGED)
    return HeartbeatResultOut.of(result)


@router.post("/job-requests", response_model=JobRequestResultOut, operation_id="runner_request_job")
def request_job(principal: CurrentPrincipal, deps: Deps) -> JobRequestResultOut:
    """割り当ての要求。割り当てなしも成功(200)で返す。"""
    result = deps.core.request_job(principal, runner_id=principal.subject_id)
    if result.assignment is not None:
        deps.publisher.job_assigned(result.assignment.job_id)
    deps.publisher.runner_event(principal.subject_id)
    return JobRequestResultOut.of(result)


@router.post("/jobs/{job_id}/result", response_model=FinishResultOut, operation_id="runner_report_finished")
def report_finished(job_id: str, body: FinishRequest, principal: CurrentPrincipal, deps: Deps) -> FinishResultOut:
    """終了の報告。"""
    result = deps.core.report_finished(
        principal,
        runner_id=principal.subject_id,
        job_id=job_id,
        outcome=body.outcome,
        result_summary=body.result_summary,
    )
    deps.publisher.job_finished(result)
    deps.publisher.runner_event(principal.subject_id)
    return FinishResultOut.of(result)


@router.post("/jobs/{job_id}/stopped", response_model=FinishResultOut, operation_id="runner_confirm_stopped")
def confirm_stopped(job_id: str, principal: CurrentPrincipal, deps: Deps) -> FinishResultOut:
    """中断の要求に対する、停止の確認。"""
    result = deps.core.confirm_stopped(principal, runner_id=principal.subject_id, job_id=job_id)
    deps.publisher.job_finished(result)
    deps.publisher.runner_event(principal.subject_id)
    return FinishResultOut.of(result)
