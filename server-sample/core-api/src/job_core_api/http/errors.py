"""エラーの写像(research.md R7、contracts/http-api.md §3)。

すべての失敗を `application/problem+json`(RFC 9457)にする。`code` ごとに、状態コード・固定の短い文・固定の詳細・
追加の項目(許可した項目だけ)を表で定める。**例外の文字列は応答に出さない**(T-A8)。
表にない例外は `500 internal_error`(詳細なし。内容は request_id つきでサーバーのログにだけ出す)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from job_core.runner.domain.errors import InvalidDeclaration
from job_core.shared.errors import JobCoreError

from ..access.config import AccessConfigInvalid
from ..access.credentials import CredentialNotFoundError
from ..access.ports import DuplicateCredentialName, IdentityProviderUnavailable

logger = logging.getLogger("job_core_api.errors")

PROBLEM_CONTENT_TYPE = "application/problem+json"
TYPE_PREFIX = "urn:job-api:error:"
MAX_LOCATION_TEXT = 64


class ApiError(Exception):
    """API の層が加える拒否。code は PROBLEMS の表にあるもの。追加の項目は固定の名前だけ。"""

    code: str = "internal_error"

    def __init__(self, **extras: Any) -> None:
        super().__init__(self.code)  # 例外の文字列は応答に出さない(code だけ)
        self.extras = extras


class RequestInvalid(ApiError):
    code = "request_invalid"

    def __init__(self, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(errors=errors or [])


class ReturnToInvalid(ApiError):
    code = "return_to_invalid"


class AuthenticationRequired(ApiError):
    code = "authentication_failed"


class NetworkNotAllowed(ApiError):
    code = "network_not_allowed"


class OriginNotAllowed(ApiError):
    code = "origin_not_allowed"


class PayloadTooLarge(ApiError):
    code = "payload_too_large"


class SseCapacityExceeded(ApiError):
    code = "sse_capacity_exceeded"


class SourceNotAvailableError(ApiError):
    """取得資格の発行元がない構成(004)。"""

    code = "source_not_available"


class MethodNotAllowed(ApiError):
    code = "method_not_allowed"


class NotFound(ApiError):
    """ルートが存在しない(例: 遷移の要らない認証方式の `begin_login`)。"""

    code = "not_found"


@dataclass(frozen=True)
class ProblemSpec:
    status: int
    title: str
    detail: str
    extras: Mapping[str, Callable[[Any], Any]] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)


def _attr(name: str) -> Callable[[Any], Any]:
    return lambda exc: getattr(exc, name)


def _extra(name: str) -> Callable[[Any], Any]:
    return lambda exc: exc.extras.get(name)


def _violations(exc: InvalidDeclaration) -> list[dict[str, str]]:
    return [{"key": key, "reason": reason} for key, reason in exc.violations]


def _access_violations(exc: AccessConfigInvalid) -> list[dict[str, str]]:
    return [{"key": v.location, "reason": v.reason} for v in exc.violations]


_BEARER = {"WWW-Authenticate": "Bearer"}

# code → 仕様。001・002 のコアの code はそのまま使う(contracts/http-api.md §3.1)。
PROBLEMS: dict[str, ProblemSpec] = {
    "request_invalid": ProblemSpec(
        400, "要求の形式が不正", "要求の形式が定義に合わない。", {"errors": _extra("errors")}
    ),
    "access_config_invalid": ProblemSpec(
        400,
        "アクセス設定が不正",
        "アクセス設定が検証に通らない。現在の対応表は変わらない。",
        {"violations": _access_violations},
    ),
    "return_to_invalid": ProblemSpec(400, "戻り先が不正", "戻り先は同一オリジンの相対パスでなければならない。"),
    "authentication_failed": ProblemSpec(401, "認証に失敗", "認証に失敗した。", headers=_BEARER),
    "permission_denied": ProblemSpec(
        403, "権限がない", "この操作に必要な権限がない。", {"required_permissions": lambda e: list(e.required)}
    ),
    "network_not_allowed": ProblemSpec(403, "接続元が許可されていない", "この接続元からは利用できない。"),
    "origin_not_allowed": ProblemSpec(403, "Origin が許可されていない", "この Origin からの状態変更は許可されない。"),
    "runner_mismatch": ProblemSpec(403, "対象が一致しない", "認証した主体は、この対象を操作できない。"),
    "job_not_found": ProblemSpec(
        404, "ジョブが存在しない", "指定したジョブが存在しない。", {"job_id": _attr("job_id")}
    ),
    "runner_not_found": ProblemSpec(
        404, "ランナーが存在しない", "指定したランナーが存在しない、または削除済み。", {"runner_id": _attr("runner_id")}
    ),
    "credential_not_found": ProblemSpec(
        404, "認証情報が存在しない", "指定した認証情報が存在しない。", {"credential_id": _attr("credential_id")}
    ),
    "not_found": ProblemSpec(404, "見つからない", "指定した操作は利用できない。"),
    "method_not_allowed": ProblemSpec(405, "メソッドが許可されていない", "このパスではそのメソッドは使えない。"),
    "duplicate_queued_job": ProblemSpec(
        409, "同じ内容のジョブが待機中", "同じ内容のジョブが既に待機中。", {"existing_job_id": _attr("existing_job_id")}
    ),
    "target_not_queued": ProblemSpec(
        409,
        "対象が待機中でない",
        "対象のジョブが待機中でない。",
        {"job_id": _attr("job_id"), "from_state": _attr("state")},
    ),
    "anchor_not_queued": ProblemSpec(
        409,
        "基準のジョブが待機中でない",
        "位置の基準のジョブが待機中でない。",
        {"anchor_job_id": _attr("anchor_job_id")},
    ),
    "invalid_state_transition": ProblemSpec(
        409,
        "状態の遷移が不正",
        "現在の状態ではこの操作はできない。",
        {"from_state": _attr("from_state"), "operation": _attr("operation")},
    ),
    "abort_already_requested": ProblemSpec(
        409,
        "中断を要求済み",
        "中断の要求が既にある。",
        {"requested_at": lambda e: e.requested_at.isoformat().replace("+00:00", "Z")},
    ),
    "runner_busy": ProblemSpec(
        409, "ランナーが使用中", "ランナーに未終了のジョブがある。", {"job_id": _attr("job_id")}
    ),
    "runner_has_unfinished_job": ProblemSpec(
        409, "未終了のジョブがある", "ランナーに未終了のジョブがある。", {"job_id": _attr("job_id")}
    ),
    "duplicate_runner_name": ProblemSpec(409, "ランナー名が重複", "同じ名前のランナーが既にある。"),
    "duplicate_credential_name": ProblemSpec(409, "認証情報の名前が重複", "同じ名前の有効な認証情報が既にある。"),
    "already_in_maintenance": ProblemSpec(409, "既に maintenance", "ランナーは既に maintenance である。"),
    "not_in_maintenance": ProblemSpec(409, "maintenance ではない", "ランナーは maintenance ではない。"),
    "runner_deleted": ProblemSpec(409, "ランナーは削除済み", "ランナーは削除済み。"),
    "lease_expired": ProblemSpec(409, "リースの期限切れ", "リースは期限を過ぎている。"),
    "invalid_lease_transition": ProblemSpec(409, "リースの遷移が不正", "現在のリースの状態ではこの操作はできない。"),
    "concurrency_conflict": ProblemSpec(
        409, "同時の更新と衝突", "同時の更新と衝突した。再試行してよい。", headers={"Retry-After": "1"}
    ),
    "target_not_running": ProblemSpec(
        409,
        "対象が実行中でない",
        "対象のジョブが実行中でない。",
        {"job_id": _attr("job_id"), "from_state": _attr("state")},
    ),
    "log_seq_conflict": ProblemSpec(
        409, "ログの seq が衝突", "同じ seq で内容が異なるログのチャンクがある。", {"job_id": _attr("job_id")}
    ),
    "log_quota_exceeded": ProblemSpec(
        409, "ログの総量の上限", "ジョブごとのログの総量の上限を超える。", {"job_id": _attr("job_id")}
    ),
    "payload_too_large": ProblemSpec(413, "本文が大きすぎる", "要求の本文が上限を超えている。"),
    "validation_failed": ProblemSpec(
        422,
        "入力が規則を満たさない",
        "入力が規則を満たさない。",
        {"field": _attr("field"), "reason": _attr("detail")},
    ),
    "source_not_available": ProblemSpec(422, "取得資格を発行できない", "ソースの取得資格の発行元がない。"),
    "no_eligible_runner": ProblemSpec(422, "満たせるランナーがない", "要件を満たしうるランナーが登録されていない。"),
    "self_anchor": ProblemSpec(422, "自分自身は基準にできない", "自分自身を基準にした移動はできない。"),
    "reason_required": ProblemSpec(422, "理由が必要", "実行中のジョブの強制中断には理由が必要。"),
    "invalid_declaration": ProblemSpec(
        422, "能力の申告が不正", "能力の申告が許可リストに合わない。", {"violations": _violations}
    ),
    "invalid_requirement": ProblemSpec(422, "要件が不正", "ランナー要件が文法に合わない。"),
    "runner_not_registered": ProblemSpec(422, "ランナーが未登録", "ランナーはまだ登録していない。"),
    "internal_error": ProblemSpec(500, "内部のエラー", "内部のエラーが発生した。"),
    "identity_provider_unavailable": ProblemSpec(503, "認証基盤が使えない", "認証基盤が利用できない。"),
    "sse_capacity_exceeded": ProblemSpec(503, "購読の上限", "購読の接続数が上限に達している。"),
}

# 例外の型 → code(JobCoreError はその code をそのまま使う。それ以外の型だけ列挙する)
_TYPE_CODES: dict[type[BaseException], str] = {
    AccessConfigInvalid: "access_config_invalid",
    CredentialNotFoundError: "credential_not_found",
    DuplicateCredentialName: "duplicate_credential_name",
    IdentityProviderUnavailable: "identity_provider_unavailable",
}


@dataclass(frozen=True)
class Problem:
    """application/problem+json の本文(data-model.md §4)。"""

    type: str
    title: str
    status: int
    code: str
    detail: str
    request_id: str
    extras: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
            "request_id": self.request_id,
        }
        body.update(self.extras)
        return body


def code_of(exc: BaseException) -> str:
    """例外から code を決める。写像の表にないものは internal_error。"""
    if isinstance(exc, ApiError):
        return exc.code if exc.code in PROBLEMS else "internal_error"
    for exc_type, code in _TYPE_CODES.items():
        if isinstance(exc, exc_type):
            return code
    if isinstance(exc, JobCoreError) and exc.code in PROBLEMS:
        return exc.code
    return "internal_error"


def problem_for(exc: BaseException, request_id: str) -> tuple[Problem, Mapping[str, str]]:
    """例外を Problem と追加のヘッダに写す。未知の例外はログにだけ内容を出す。"""
    code = code_of(exc)
    if code == "internal_error":
        logger.error("unhandled exception request_id=%s type=%s", request_id, type(exc).__name__, exc_info=exc)
    spec = PROBLEMS[code]
    extras: dict[str, Any] = {}
    if code != "internal_error":
        for name, getter in spec.extras.items():
            try:
                value = getter(exc)
            except (AttributeError, KeyError):
                continue
            if value is not None:
                extras[name] = value
    problem = Problem(
        type=TYPE_PREFIX + code,
        title=spec.title,
        status=spec.status,
        code=code,
        detail=spec.detail,
        request_id=request_id,
        extras=extras,
    )
    return problem, dict(spec.headers)


def validation_errors(errors: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """FastAPI(pydantic)の検証エラーを、位置と理由の種類だけにする(値を含めない)。"""
    result: list[dict[str, Any]] = []
    for error in errors:
        location = [
            item if isinstance(item, int) else str(item)[:MAX_LOCATION_TEXT]
            for item in error.get("loc", ())
            if item != "body"
        ]
        result.append({"location": location, "reason": str(error.get("type", "invalid"))[:MAX_LOCATION_TEXT]})
    return result[:50]


CredentialNotFound = CredentialNotFoundError

__all__ = [
    "PROBLEMS",
    "PROBLEM_CONTENT_TYPE",
    "ApiError",
    "AuthenticationRequired",
    "CredentialNotFound",
    "MethodNotAllowed",
    "NetworkNotAllowed",
    "NotFound",
    "OriginNotAllowed",
    "PayloadTooLarge",
    "Problem",
    "RequestInvalid",
    "ReturnToInvalid",
    "SseCapacityExceeded",
    "code_of",
    "problem_for",
    "validation_errors",
]
