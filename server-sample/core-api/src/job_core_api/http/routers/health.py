"""運用: 生存の確認(contracts/http-api.md §2.8)。依存を見ない。接続元の許可リストは適用される。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["ops"])


class HealthStatus(BaseModel):
    status: str


@router.get("/healthz", response_model=HealthStatus, operation_id="healthz")
def healthz() -> HealthStatus:
    return HealthStatus(status="ok")
