"""US7-1〜4: 原因を判断できるエラーを機械可読な形式で受け取る(spec US7)。"""

from __future__ import annotations

from datetime import timedelta

from job_core_api.settings import ApiSettings
from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def ready() -> tuple[ApiFixture, str, str]:
    api = build_api()
    api.register_runner()
    return api, api.member("alice"), api.admin()


def test_us7_1_no_eligible_runner_is_422_and_distinct_from_permission_errors() -> None:
    api, alice, _ = ready()
    body = submit_body(definition_requirement={"all": [{"key": "k1", "op": "eq", "value": "other"}]})
    response = api.client.post("/v1/jobs", json=body, headers=H(alice))
    assert response.status_code == 422 and response.json()["code"] == "no_eligible_runner"
    assert response.headers["content-type"].startswith("application/problem+json")
    denied = api.client.post("/v1/jobs", json=submit_body(), headers=H(api.viewer()))
    assert denied.status_code == 403 and denied.json()["code"] != response.json()["code"]


def test_us7_2_permission_denied_lists_candidate_permissions_only() -> None:
    api, alice, _ = ready()
    bob = api.member("bob")
    job = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    response = api.client.post(f"/v1/jobs/{job}/cancel", json={}, headers=H(bob))
    body = response.json()
    assert response.status_code == 403 and body["code"] == "permission_denied"
    assert set(body["required_permissions"]) == {"job.cancel_queued"}
    assert "alice" not in response.text  # 他の主体の情報を出さない(識別子を除く。ここではジョブの所有者)


def test_us7_3_invalid_transition_has_from_state_and_operation() -> None:
    api, alice, _ = ready()
    job = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    api.client.post(f"/v1/jobs/{job}/cancel", json={}, headers=H(alice))
    response = api.client.post(f"/v1/jobs/{job}/cancel", json={}, headers=H(alice))
    body = response.json()
    assert response.status_code == 409 and body["code"] == "invalid_state_transition"
    assert body["from_state"] == "cancelled" and body["operation"]


def test_us7_4_authentication_failures_do_not_reveal_the_cause() -> None:
    api, _alice, _admin = ready()
    revoked = api.member("carol")
    api.sessions.revoke_all_of("carol", api.core.clock.now())  # type: ignore[arg-type]
    expired = api.member("dave")
    api.advance(timedelta(hours=3))
    bodies = []
    for token in ("ss_unknown", "garbage", revoked, expired, "st_unknown", "rt_unknown"):
        response = api.client.get("/v1/queue", headers=H(token))
        assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
        body = response.json()
        body.pop("request_id")
        bodies.append(body)
    assert all(b == bodies[0] for b in bodies)


def test_duplicate_submission_names_the_existing_job() -> None:
    api, alice, _ = ready()
    body = submit_body(definition_source="s", definition_revision="r")
    first = api.client.post("/v1/jobs", json=body, headers=H(alice)).json()["job_id"]
    second = api.client.post("/v1/jobs", json=body, headers=H(alice))
    assert second.status_code == 409 and second.json()["code"] == "duplicate_queued_job"
    assert second.json()["existing_job_id"] == first


def test_malformed_requests_report_locations_without_values() -> None:
    api, alice, _ = ready()
    response = api.client.post(
        "/v1/jobs",
        json={"definition": {"requirement": {}, "payload": {}, "timeout_seconds": "LEAKED-VALUE"}, "placement": 5},
        headers=H(alice),
    )
    body = response.json()
    assert response.status_code == 400 and body["code"] == "request_invalid"
    assert {tuple(e["location"]) for e in body["errors"]} >= {("definition", "timeout_seconds"), ("placement",)}
    assert "LEAKED-VALUE" not in response.text
    not_json = api.client.post(
        "/v1/jobs", content=b"{not json", headers={**H(alice), "content-type": "application/json"}
    )
    assert not_json.status_code == 400 and not_json.json()["code"] == "request_invalid"


def test_oversize_body_is_413_and_unavailable_identity_provider_is_503() -> None:
    api = build_api(settings=ApiSettings(max_body_bytes=200))
    big = api.client.post("/v1/jobs", content=b"x" * 201, headers=H(api.member()))
    assert big.status_code == 413 and big.json()["code"] == "payload_too_large"
    api.identity.available = False
    unavailable = api.client.post("/v1/auth/login", json={"proof": {"subject": "u"}})
    assert unavailable.status_code == 503 and unavailable.json()["code"] == "identity_provider_unavailable"
