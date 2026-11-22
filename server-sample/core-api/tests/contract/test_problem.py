"""エラー応答の契約テスト(contracts/problem.schema.json、contracts/http-api.md §3。FR-013、SC-006、T-A1、T-A8)。

- 応答がスキーマに適合し、`code` ごとの状態コードが表と一致する。
- スキーマの `code` の列挙のすべてが写像の表にあり、各 `code` を起こす最小の操作が 1 つ以上ある
  (公開の操作から起こせないものは、理由つきで除外する)。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import jsonschema
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from job_core_api.access.config import AccessConfig
from job_core_api.http.errors import PROBLEMS
from job_core_api.settings import ApiSettings
from job_testing.api_fakes import ApiFixture, build_api, submit_body
from job_testing.contracts.access_config import variant

H = ApiFixture.headers
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "specs/003-core-api/contracts/problem.schema.json").read_text("utf-8")
)


def ready() -> tuple[ApiFixture, str, str, str, str]:
    api = build_api()
    api.register_runner()
    return api, api.admin(), api.member("alice"), api.operator("op"), api.viewer()


def new_job(api: ApiFixture, token: str, n: int = 1) -> str:
    response = api.client.post("/v1/jobs", json=submit_body(definition_payload={"n": n}), headers=H(token))
    return response.json()["job_id"]  # type: ignore[no-any-return]


def t_request_invalid() -> httpx.Response:
    api, _, alice, *_ = ready()
    return api.client.post("/v1/jobs", json={}, headers=H(alice))


def t_access_config_invalid() -> httpx.Response:
    api, admin, *_ = ready()
    api.access_source.replace(lambda: AccessConfig.from_mapping(variant(groups={"g": ["nope"]})))
    return api.client.post("/v1/access/reload", headers=H(admin))


def t_return_to_invalid() -> httpx.Response:
    return build_api().client.get("/v1/auth/login", params={"return_to": "//evil.example"}, follow_redirects=False)


def t_authentication_failed() -> httpx.Response:
    return build_api().client.get("/v1/queue")


def t_permission_denied() -> httpx.Response:
    api, _, _, _, viewer = ready()
    return api.client.post("/v1/jobs", json=submit_body(), headers=H(viewer))


def t_network_not_allowed() -> httpx.Response:
    return build_api(settings=ApiSettings(allowed_networks=("203.0.113.0/24",))).client.get("/healthz")


def t_origin_not_allowed() -> httpx.Response:
    api = build_api(settings=ApiSettings(cookie_secure=False))
    api.client.cookies.set("session", api.member())
    return api.client.delete("/v1/auth/session")


def t_job_not_found() -> httpx.Response:
    api, _, alice, *_ = ready()
    return api.client.get("/v1/jobs/none", headers=H(alice))


def t_runner_not_found() -> httpx.Response:
    api, _, alice, *_ = ready()
    return api.client.get("/v1/runners/none", headers=H(alice))


def t_credential_not_found() -> httpx.Response:
    api, admin, *_ = ready()
    return api.client.delete("/v1/service-credentials/none", headers=H(admin))


def t_duplicate_queued_job() -> httpx.Response:
    api, _, alice, *_ = ready()
    body = submit_body(definition_source="s1", definition_revision="rev1")
    api.client.post("/v1/jobs", json=body, headers=H(alice))
    return api.client.post("/v1/jobs", json=body, headers=H(alice))


def t_target_not_queued() -> httpx.Response:
    api, _, alice, op, _ = ready()
    a, b = new_job(api, alice, 1), new_job(api, alice, 2)
    api.client.post(f"/v1/jobs/{a}/cancel", json={}, headers=H(alice))
    return api.client.post(
        f"/v1/jobs/{a}/reschedule", json={"placement": {"anchor_job_id": b, "side": "before"}}, headers=H(op)
    )


def t_anchor_not_queued() -> httpx.Response:
    api, _, alice, op, _ = ready()
    a, b = new_job(api, alice, 1), new_job(api, alice, 2)
    api.client.post(f"/v1/jobs/{b}/cancel", json={}, headers=H(alice))
    return api.client.post(
        f"/v1/jobs/{a}/reschedule", json={"placement": {"anchor_job_id": b, "side": "before"}}, headers=H(op)
    )


def t_invalid_state_transition() -> httpx.Response:
    api, _, alice, *_ = ready()
    return api.client.post(f"/v1/jobs/{new_job(api, alice)}/retry", json={}, headers=H(alice))


def t_abort_already_requested() -> httpx.Response:
    api = build_api()
    runner_id, token = api.register_runner()
    alice, op = api.member("alice"), api.operator("op")
    job = new_job(api, alice)
    api.assign_next(runner_id, token)
    api.client.post(f"/v1/jobs/{job}/cancel", json={"reason": "r"}, headers=H(op))
    return api.client.post(f"/v1/jobs/{job}/cancel", json={"reason": "r"}, headers=H(op))


def t_runner_has_unfinished_job() -> httpx.Response:
    api = build_api()
    runner_id, token = api.register_runner()
    new_job(api, api.member("alice"))
    api.assign_next(runner_id, token)
    return api.client.delete(f"/v1/runners/{runner_id}", headers=H(api.admin()))


def t_duplicate_runner_name() -> httpx.Response:
    api, admin, *_ = ready()
    return api.client.post("/v1/runners", json={"name": "r-a"}, headers=H(admin))


def t_duplicate_credential_name() -> httpx.Response:
    api, admin, *_ = ready()
    body = {"name": "svc", "permissions": []}
    api.client.post("/v1/service-credentials", json=body, headers=H(admin))
    return api.client.post("/v1/service-credentials", json=body, headers=H(admin))


def t_payload_too_large() -> httpx.Response:
    api = build_api(settings=ApiSettings(max_body_bytes=100))
    return api.client.post("/v1/jobs", content=b"x" * 101, headers=H(api.member()))


def t_validation_failed() -> httpx.Response:
    api, admin, *_ = ready()
    return api.client.post("/v1/runners", json={"name": ""}, headers=H(admin))


def t_no_eligible_runner() -> httpx.Response:
    api, _, alice, *_ = ready()
    body = submit_body(definition_requirement={"all": [{"key": "k1", "op": "eq", "value": "other"}]})
    return api.client.post("/v1/jobs", json=body, headers=H(alice))


def t_self_anchor() -> httpx.Response:
    api, _, alice, op, _ = ready()
    job = new_job(api, alice)
    return api.client.post(
        f"/v1/jobs/{job}/reschedule", json={"placement": {"anchor_job_id": job, "side": "before"}}, headers=H(op)
    )


def t_reason_required() -> httpx.Response:
    api = build_api()
    runner_id, token = api.register_runner()
    job = new_job(api, api.member("alice"))
    api.assign_next(runner_id, token)
    return api.client.post(f"/v1/jobs/{job}/cancel", json={}, headers=H(api.operator("op")))


def t_invalid_declaration() -> httpx.Response:
    api = build_api()
    created = api.client.post("/v1/runners", json={"name": "r-x"}, headers=H(api.admin())).json()
    return api.client.post(
        "/v1/runner/registration", json={"capabilities": {"nokey": "v"}}, headers=H(created["token"]["token"])
    )


def t_runner_not_registered() -> httpx.Response:
    api = build_api()
    created = api.client.post("/v1/runners", json={"name": "r-x"}, headers=H(api.admin())).json()
    return api.client.post("/v1/runner/heartbeat", headers=H(created["token"]["token"]))


def t_runner_mismatch() -> httpx.Response:
    api = build_api()
    runner_id, token = api.register_runner("r-a")
    _, other_token = api.register_runner("r-b")
    job = new_job(api, api.member("alice"))
    api.assign_next(runner_id, token)
    return api.client.post(f"/v1/runner/jobs/{job}/result", json={"outcome": "succeeded"}, headers=H(other_token))


def t_already_in_maintenance() -> httpx.Response:
    api = build_api()
    runner_id, _ = api.register_runner("r-a")
    admin = api.admin()
    api.client.put(f"/v1/runners/{runner_id}/maintenance", json={}, headers=H(admin))
    return api.client.put(f"/v1/runners/{runner_id}/maintenance", json={}, headers=H(admin))


def t_internal_error() -> httpx.Response:
    api = build_api()
    router = APIRouter()

    @router.get("/v1/_boom")
    def boom() -> None:
        raise RuntimeError("secret")

    api.app.include_router(router)
    return TestClient(api.app, client=("127.0.0.1", 1), raise_server_exceptions=False).get("/v1/_boom")


def t_identity_provider_unavailable() -> httpx.Response:
    api = build_api()
    api.identity.available = False
    return api.client.post("/v1/auth/login", json={"proof": {"subject": "u1"}})


def t_not_found() -> httpx.Response:
    return build_api().client.get("/v1/auth/login", follow_redirects=False)  # 遷移の要らない方式


def t_method_not_allowed() -> httpx.Response:
    return build_api().client.post("/healthz")


TRIGGERS: dict[str, Callable[[], httpx.Response]] = {
    name.removeprefix("t_"): fn for name, fn in list(globals().items()) if name.startswith("t_")
}

# 公開の操作からは起こせない code と、その理由(コアの防御的な拒否。別の検査で確かめる)
UNREACHABLE: dict[str, str] = {
    "runner_busy": "割り当ての要求は、使用中のランナーに対して拒否ではなく『割り当てなし』を返す(002)",
    "runner_deleted": "削除済みのランナーは runner_not_found として扱われる",
    "not_in_maintenance": "同上(コアの拒否の写像は test_error_mapping で確かめる)",
    "invalid_requirement": "要件は提出時に検証され、ランナー側の判定には文法に合わないものが渡らない",
    "lease_expired": "コアの内部の拒否",
    "invalid_lease_transition": "コアの内部の拒否",
    "concurrency_conflict": "再試行を使い切った場合だけ。test_error_mapping で写像と Retry-After を確かめる",
    "sse_capacity_exceeded": "ループバックの実サーバーが要る。test_events で確かめる",
}


def validate(response: httpx.Response) -> dict[str, object]:
    assert response.headers["content-type"].startswith("application/problem+json"), response.text
    body = response.json()
    jsonschema.validate(body, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert body["request_id"] == response.headers["x-request-id"]
    return body  # type: ignore[no-any-return]


@pytest.mark.parametrize("code", sorted(TRIGGERS))
def test_each_trigger_yields_its_code_status_and_a_schema_valid_problem(code: str) -> None:
    response = TRIGGERS[code]()
    body = validate(response)
    assert body["code"] == code
    assert response.status_code == PROBLEMS[code].status == body["status"]
    for header, value in PROBLEMS[code].headers.items():
        assert response.headers[header.lower()] == value


def test_every_schema_code_has_a_trigger_or_a_documented_reason() -> None:
    enum = set(SCHEMA["properties"]["code"]["enum"])
    assert enum == set(PROBLEMS), "スキーマの列挙と写像の表が一致しない"
    missing = enum - set(TRIGGERS) - set(UNREACHABLE)
    assert missing == set(), f"code を起こす操作がない: {sorted(missing)}"
    assert not set(TRIGGERS) & set(UNREACHABLE)
    assert all(reason.strip() for reason in UNREACHABLE.values())


def test_status_codes_follow_the_contract_table() -> None:
    contract = Path(__file__).resolve().parents[3] / "specs/003-core-api/contracts/http-api.md"
    text = contract.read_text("utf-8")
    for code, spec in PROBLEMS.items():
        row = next((line for line in text.splitlines() if f"`{code}`" in line and line.startswith("| `")), None)
        assert row is not None, code
        assert row.startswith(f"| `{spec.status}`"), (code, row)
