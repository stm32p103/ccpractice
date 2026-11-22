"""エラー応答の OpenAPI 上のモデル(contracts/problem.schema.json)。実際の本文は errors.Problem が作る。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ProblemOut(BaseModel):
    """`application/problem+json`(RFC 9457)。追加の項目は `code` ごとに固定。"""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    code: str
    detail: str
    request_id: str
    required_permissions: list[str] | None = None
    existing_job_id: str | None = None
    anchor_job_id: str | None = None
    job_id: str | None = None
    runner_id: str | None = None
    credential_id: str | None = None
    from_state: str | None = None
    operation: str | None = None
    requested_at: str | None = None
    field: str | None = None
    reason: str | None = None
    violations: list[dict[str, Any]] | None = None
    errors: list[dict[str, Any]] | None = None


PROBLEM_STATUSES: dict[int | str, str] = {
    400: "要求の形式が不正",
    401: "認証に失敗",
    403: "権限がない・接続元または Origin が許可されていない",
    404: "対象が存在しない",
    409: "現在の状態では実行できない・重複・同時の更新との衝突",
    413: "本文が大きすぎる",
    422: "入力が規則を満たさない",
    500: "内部のエラー",
    503: "認証基盤が使えない・購読の上限",
}

PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ProblemOut, "description": description} for status, description in PROBLEM_STATUSES.items()
}
