"""能力の許可リストのルーター(contracts/http-api.md §2.3。002)。"""

from __future__ import annotations

from fastapi import APIRouter

from ..authn import CurrentPrincipal, Deps
from ..schemas_runners import AllowlistOut, ReplaceAllowlistRequest

router = APIRouter(prefix="/capability-allowlist", tags=["runners"])


@router.get("", response_model=AllowlistOut, operation_id="get_capability_allowlist")
def get_allowlist(principal: CurrentPrincipal, deps: Deps) -> AllowlistOut:
    """ランナーが申告してよい能力のキーの許可リスト。"""
    return AllowlistOut.of(deps.core.get_allowlist(principal))


@router.put("", response_model=AllowlistOut, operation_id="replace_capability_allowlist")
def replace_allowlist(body: ReplaceAllowlistRequest, principal: CurrentPrincipal, deps: Deps) -> AllowlistOut:
    """許可リストを置き換える(既存のランナーの能力は変えない)。"""
    entries = {key: kind.value for key, kind in body.entries.items()}
    return AllowlistOut.of(deps.core.replace_allowlist(principal, entries=entries, reason=body.reason))
