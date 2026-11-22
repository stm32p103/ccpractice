"""エラーの写像(research.md R7、contracts/http-api.md §3)。"""

from __future__ import annotations

import importlib
import json
import pkgutil
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

import job_core
from job_core.job.domain.errors import (
    AbortAlreadyRequested,
    DuplicateQueuedJob,
    InvalidStateTransition,
    PermissionDenied,
    ValidationFailed,
)
from job_core.runner.domain.errors import InvalidDeclaration
from job_core.shared.errors import JobCoreError
from job_core_api.access.config import AccessConfigInvalid, Violation
from job_core_api.http.errors import PROBLEMS, ApiError, CredentialNotFound, code_of, problem_for, validation_errors

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "specs/003-core-api/contracts/problem.schema.json").read_text("utf-8")
)


def all_core_error_classes() -> list[type[JobCoreError]]:
    for module in pkgutil.walk_packages(job_core.__path__, "job_core."):
        importlib.import_module(module.name)
    found: list[type[JobCoreError]] = []
    todo = [JobCoreError]
    while todo:
        current = todo.pop()
        for sub in current.__subclasses__():
            found.append(sub)
            todo.append(sub)
    return found


def test_every_core_error_code_is_in_the_mapping_table() -> None:
    missing = [c.__name__ for c in all_core_error_classes() if c.code not in PROBLEMS]
    assert missing == []


def test_every_table_code_is_declared_in_the_schema_enum() -> None:
    enum = set(SCHEMA["properties"]["code"]["enum"])
    assert set(PROBLEMS) - enum == set()


def test_status_codes_match_the_contract() -> None:
    expected = {
        "request_invalid": 400,
        "access_config_invalid": 400,
        "return_to_invalid": 400,
        "authentication_failed": 401,
        "permission_denied": 403,
        "network_not_allowed": 403,
        "origin_not_allowed": 403,
        "job_not_found": 404,
        "runner_not_found": 404,
        "credential_not_found": 404,
        "duplicate_queued_job": 409,
        "target_not_queued": 409,
        "anchor_not_queued": 409,
        "invalid_state_transition": 409,
        "abort_already_requested": 409,
        "runner_busy": 409,
        "runner_has_unfinished_job": 409,
        "duplicate_runner_name": 409,
        "duplicate_credential_name": 409,
        "concurrency_conflict": 409,
        "payload_too_large": 413,
        "validation_failed": 422,
        "no_eligible_runner": 422,
        "self_anchor": 422,
        "reason_required": 422,
        "invalid_declaration": 422,
        "runner_not_registered": 422,
        "internal_error": 500,
        "identity_provider_unavailable": 503,
        "sse_capacity_exceeded": 503,
    }
    for code, status in expected.items():
        assert PROBLEMS[code].status == status, code


def validate(problem_json: dict[str, object]) -> None:
    jsonschema.validate(problem_json, SCHEMA, format_checker=jsonschema.FormatChecker())


def test_permission_denied_has_required_permissions_only() -> None:
    problem, _ = problem_for(PermissionDenied(["queue.schedule", "job.submit"]), "req-1")
    body = problem.to_json()
    validate(body)
    assert body["status"] == 403 and body["code"] == "permission_denied"
    assert body["required_permissions"] == ["queue.schedule", "job.submit"]
    assert set(body) == {"type", "title", "status", "code", "detail", "request_id", "required_permissions"}


def test_extras_are_fixed_per_code() -> None:
    cases = [
        (DuplicateQueuedJob("j1"), {"existing_job_id": "j1"}),
        (InvalidStateTransition("succeeded", "cancel"), {"from_state": "succeeded", "operation": "cancel"}),
        (
            AbortAlreadyRequested(datetime(2026, 1, 1, 9, 0, tzinfo=UTC)),
            {"requested_at": "2026-01-01T09:00:00Z"},
        ),
        (ValidationFailed("name", "1〜5 文字"), {"field": "name", "reason": "1〜5 文字"}),
        (InvalidDeclaration([("k1", "not_allowed")]), {"violations": [{"key": "k1", "reason": "not_allowed"}]}),
        (CredentialNotFound("c1"), {"credential_id": "c1"}),
    ]
    for exc, extras in cases:
        problem, _ = problem_for(exc, "req-1")
        body = problem.to_json()
        validate(body)
        fixed = {"type", "title", "status", "code", "detail", "request_id"}
        assert {k: body[k] for k in body if k not in fixed} == extras


def test_detail_is_fixed_text_and_never_the_exception_string() -> None:
    secret = "ss_secret-token-value"
    problem, _ = problem_for(ValidationFailed("f", secret), "req-1")
    assert secret not in problem.detail
    problem, _ = problem_for(JobCoreError(secret), "req-1")  # 表にない基底の例外
    assert problem.code == "internal_error" and secret not in json.dumps(problem.to_json())


def test_unknown_exception_is_internal_error_without_details() -> None:
    problem, headers = problem_for(RuntimeError("password=hunter2 /etc/internal"), "req-9")
    body = problem.to_json()
    validate(body)
    assert body["status"] == 500 and body["code"] == "internal_error"
    assert "hunter2" not in json.dumps(body) and body["request_id"] == "req-9"
    assert headers == {}


def test_headers_for_401_and_conflict() -> None:
    from job_core.job.domain.errors import ConcurrencyConflict
    from job_core_api.http.errors import AuthenticationRequired

    assert problem_for(AuthenticationRequired(), "r")[1] == {"WWW-Authenticate": "Bearer"}
    assert problem_for(ConcurrencyConflict(), "r")[1] == {"Retry-After": "1"}


def test_access_config_invalid_lists_locations_and_reasons_only() -> None:
    exc = AccessConfigInvalid([Violation("roles.r", "未定義のロールの参照")])
    problem, _ = problem_for(exc, "r")
    assert problem.to_json()["violations"] == [{"key": "roles.r", "reason": "未定義のロールの参照"}]


def test_validation_errors_contain_no_input_values() -> None:
    errors = [
        {"loc": ("body", "definition", "payload", 0), "type": "string_too_short", "msg": "x", "input": "SECRET"},
        {"loc": ("query", "limit"), "type": "int_parsing", "input": "SECRET"},
    ]
    result = validation_errors(errors)  # type: ignore[arg-type]
    assert result == [
        {"location": ["definition", "payload", 0], "reason": "string_too_short"},
        {"location": ["query", "limit"], "reason": "int_parsing"},
    ]
    assert "SECRET" not in json.dumps(result)


def test_code_of_api_errors_outside_the_table_is_internal() -> None:
    class Weird(ApiError):
        code = "not_in_table"

    assert code_of(Weird()) == "internal_error"


@pytest.mark.parametrize("code", sorted(PROBLEMS))
def test_every_table_entry_renders_a_valid_problem(code: str) -> None:
    class Dummy(ApiError):
        pass

    Dummy.code = code
    problem, _ = problem_for(Dummy(), "req-1")
    assert problem.code == code
    validate(problem.to_json())
