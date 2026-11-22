"""ランナーの管理のルーター(contracts/http-api.md §2.3。002)。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from ...events.ports import ChangeKind
from ..authn import CurrentPrincipal, Deps
from ..schemas_audit import AuditRecordOut
from ..schemas_runners import (
    CreatedRunnerOut,
    CreateRunnerRequest,
    IssuedTokenOut,
    MaintenanceRequest,
    RunnerOut,
)

router = APIRouter(prefix="/runners", tags=["runners"])

ReasonQuery = Annotated[str | None, Query(description="理由(任意。監査ログに残る)")]


@router.post("", status_code=201, response_model=CreatedRunnerOut, operation_id="create_runner")
def create_runner(
    body: CreateRunnerRequest, response: Response, principal: CurrentPrincipal, deps: Deps
) -> CreatedRunnerOut:
    """ランナーを作成し、トークンを発行する。トークンの値はこの応答だけで返る。"""
    created = deps.core.create_runner(principal, name=body.name)
    response.headers["Location"] = f"/v1/runners/{created.runner_id}"
    deps.publisher.runner_event(created.runner_id, ChangeKind.CREATED)
    return CreatedRunnerOut.of(created)


@router.get("", response_model=list[RunnerOut], operation_id="list_runners")
def list_runners(principal: CurrentPrincipal, deps: Deps) -> list[RunnerOut]:
    """ランナーの一覧(名前の順。トークンの情報を含まない)。"""
    return [RunnerOut.of(view) for view in deps.core.list_runners(principal)]


@router.get("/{runner_id}", response_model=RunnerOut, operation_id="get_runner")
def get_runner(runner_id: str, principal: CurrentPrincipal, deps: Deps) -> RunnerOut:
    return RunnerOut.of(deps.core.get_runner(principal, runner_id=runner_id))


@router.get("/{runner_id}/history", response_model=list[AuditRecordOut], operation_id="get_runner_history")
def get_runner_history(runner_id: str, principal: CurrentPrincipal, deps: Deps) -> list[AuditRecordOut]:
    """ランナーの操作の経緯。"""
    return [AuditRecordOut.of(r) for r in deps.core.get_runner_history(principal, runner_id=runner_id)]


@router.put("/{runner_id}/maintenance", response_model=RunnerOut, operation_id="set_runner_maintenance")
def set_maintenance(runner_id: str, body: MaintenanceRequest, principal: CurrentPrincipal, deps: Deps) -> RunnerOut:
    """ランナーを maintenance にする(割り当ての対象から外す)。"""
    view = deps.core.set_maintenance(principal, runner_id=runner_id, reason=body.reason)
    deps.publisher.runner_event(runner_id, ChangeKind.MAINTENANCE_CHANGED)
    return RunnerOut.of(view)


@router.delete("/{runner_id}/maintenance", response_model=RunnerOut, operation_id="clear_runner_maintenance")
def clear_maintenance(runner_id: str, principal: CurrentPrincipal, deps: Deps, reason: ReasonQuery = None) -> RunnerOut:
    view = deps.core.clear_maintenance(principal, runner_id=runner_id, reason=reason)
    deps.publisher.runner_event(runner_id, ChangeKind.MAINTENANCE_CHANGED)
    return RunnerOut.of(view)


@router.delete("/{runner_id}/fault", response_model=RunnerOut, operation_id="clear_runner_fault")
def clear_fault(runner_id: str, principal: CurrentPrincipal, deps: Deps, reason: ReasonQuery = None) -> RunnerOut:
    """異常を手動で解除する。"""
    view = deps.core.clear_fault(principal, runner_id=runner_id, reason=reason)
    deps.publisher.runner_event(runner_id, ChangeKind.FAULT_CHANGED)
    return RunnerOut.of(view)


@router.delete("/{runner_id}", status_code=204, operation_id="delete_runner")
def delete_runner(runner_id: str, principal: CurrentPrincipal, deps: Deps, reason: ReasonQuery = None) -> Response:
    """ランナーを削除する(未終了のジョブがあれば拒否)。"""
    deps.core.delete_runner(principal, runner_id=runner_id, reason=reason)
    deps.publisher.runner_event(runner_id, ChangeKind.DELETED)
    return Response(status_code=204)


@router.post("/{runner_id}/token", response_model=IssuedTokenOut, operation_id="reissue_runner_token")
def reissue_token(
    runner_id: str, principal: CurrentPrincipal, deps: Deps, reason: ReasonQuery = None
) -> IssuedTokenOut:
    """トークンを再発行する(旧は即時に失効)。値はこの応答だけで返る。"""
    return IssuedTokenOut.of(deps.core.reissue_token(principal, runner_id=runner_id, reason=reason))


@router.delete("/{runner_id}/token", status_code=204, operation_id="revoke_runner_token")
def revoke_token(runner_id: str, principal: CurrentPrincipal, deps: Deps, reason: ReasonQuery = None) -> Response:
    """トークンを失効させる(即時)。"""
    deps.core.revoke_token(principal, runner_id=runner_id, reason=reason)
    return Response(status_code=204)
