"""アクセスの管理のルーター(contracts/http-api.md §2.5)。権限 `access.manage`。"""

from __future__ import annotations

from fastapi import APIRouter, Response

from ..authn import CurrentPrincipal, Deps
from ..schemas_access import (
    AccessMappingOut,
    IssueCredentialRequest,
    IssuedServiceCredentialOut,
    ReloadResultOut,
    ServiceCredentialOut,
)

router = APIRouter(tags=["access"])


@router.post(
    "/service-credentials",
    status_code=201,
    response_model=IssuedServiceCredentialOut,
    operation_id="issue_service_credential",
)
def issue_service_credential(
    body: IssueCredentialRequest, response: Response, principal: CurrentPrincipal, deps: Deps
) -> IssuedServiceCredentialOut:
    """サービス用の認証情報を発行する。値はこの応答だけで返る。"""
    issued = deps.service_credentials.issue(principal, name=body.name, permissions=body.permissions)
    response.headers["Location"] = f"/v1/service-credentials/{issued.credential_id}"
    return IssuedServiceCredentialOut.of(issued)


@router.get("/service-credentials", response_model=list[ServiceCredentialOut], operation_id="list_service_credentials")
def list_service_credentials(principal: CurrentPrincipal, deps: Deps) -> list[ServiceCredentialOut]:
    """サービス用の認証情報の一覧(値・ハッシュを含まない)。"""
    return [ServiceCredentialOut.of(view) for view in deps.service_credentials.list_all(principal)]


@router.delete("/service-credentials/{credential_id}", status_code=204, operation_id="revoke_service_credential")
def revoke_service_credential(credential_id: str, principal: CurrentPrincipal, deps: Deps) -> Response:
    """サービス用の認証情報を失効させる(即時)。"""
    deps.service_credentials.revoke(principal, credential_id=credential_id)
    return Response(status_code=204)


@router.get("/access/mapping", response_model=AccessMappingOut, operation_id="get_access_mapping")
def get_access_mapping(principal: CurrentPrincipal, deps: Deps) -> AccessMappingOut:
    """現在の対応表(ロール → 権限、所属グループ → ロール、上限、digest)。"""
    return AccessMappingOut.of(deps.access_reloader.current(principal))


@router.post("/access/reload", response_model=ReloadResultOut, operation_id="reload_access_config")
def reload_access_config(principal: CurrentPrincipal, deps: Deps) -> ReloadResultOut:
    """設定ファイルを再読み込みする(検証してから差し替える。不正なら現在の対応表を保つ)。"""
    return ReloadResultOut.of(deps.access_reloader.reload(principal))


@router.delete("/access/sessions", status_code=204, operation_id="revoke_sessions_of")
def revoke_sessions_of(subject_id: str, principal: CurrentPrincipal, deps: Deps) -> Response:
    """指定した利用者のセッションをすべて失効させる。"""
    deps.session_service.revoke_all_of(principal, subject_id=subject_id)
    return Response(status_code=204)
