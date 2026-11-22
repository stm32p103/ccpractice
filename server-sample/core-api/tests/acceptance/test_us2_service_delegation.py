"""US2-1〜4: サービス主体の代理提出、失効、一般の利用者の拒否(spec US2)。"""

from __future__ import annotations

from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def issue(api: ApiFixture, admin: str, name: str, permissions: list[str]) -> str:
    response = api.client.post(
        "/v1/service-credentials", json={"name": name, "permissions": permissions}, headers=H(admin)
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def test_us2_1_service_submits_on_behalf_and_audit_records_both() -> None:
    api = build_api()
    api.register_runner()
    admin = api.admin()
    svc = issue(api, admin, "svc-a", ["job.submit", "job.submit_on_behalf"])
    response = api.client.post("/v1/jobs", json=submit_body(on_behalf_of="u2"), headers=H(svc))
    assert response.status_code == 201
    job_id = response.json()["job_id"]
    detail = api.client.get(f"/v1/jobs/{job_id}", headers=H(api.viewer("v"))).json()["summary"]
    assert detail["owner"] == "u2" and detail["submitted_by"].startswith("svc:")
    log = api.client.get("/v1/audit-log", params={"job_id": job_id}, headers=H(admin)).json()["items"]
    [record] = [r for r in log if r["operation"] == "submit"]
    assert record["on_behalf_of"] == "u2" and record["actor"].startswith("svc:") and record["actor_kind"] == "service"


def test_us2_2_ordinary_user_service_without_permission_and_runner_are_denied() -> None:
    api = build_api()
    api.register_runner()
    admin = api.admin()
    only_submit = issue(api, admin, "svc-b", ["job.submit"])
    _, runner = api.register_runner("r-b")
    for token in (api.member("alice"), only_submit, runner):
        response = api.client.post("/v1/jobs", json=submit_body(on_behalf_of="u2"), headers=H(token))
        assert response.status_code == 403, token
    denied = api.client.get("/v1/audit-log", params={"outcome": "denied"}, headers=H(admin)).json()["items"]
    assert sum(1 for r in denied if r["operation"] == "submit") >= 2
    assert all(r["on_behalf_of"] == "u2" for r in denied if r["operation"] == "submit" and r["actor_kind"] != "runner")


def test_us2_3_revoked_credential_is_unauthorized_immediately() -> None:
    api = build_api()
    admin = api.admin()
    response = api.client.post(
        "/v1/service-credentials", json={"name": "svc-a", "permissions": ["job.general"]}, headers=H(admin)
    )
    token, credential_id = response.json()["token"], response.json()["credential_id"]
    assert api.client.get("/v1/runners", headers=H(token)).status_code == 200
    assert api.client.delete(f"/v1/service-credentials/{credential_id}", headers=H(admin)).status_code == 204
    assert api.client.get("/v1/runners", headers=H(token)).status_code == 401
    assert api.client.delete(f"/v1/service-credentials/{credential_id}", headers=H(admin)).status_code == 204  # 冪等
    assert (
        api.client.delete("/v1/service-credentials/unknown", headers=H(admin)).json()["code"] == "credential_not_found"
    )
    ops = {r["operation"] for r in api.client.get("/v1/audit-log", headers=H(admin)).json()["items"]}
    assert {"service_credential_issue", "service_credential_revoke"} <= ops


def test_us2_4_the_nominal_submitter_can_cancel_own_job() -> None:
    api = build_api()
    api.register_runner()
    admin = api.admin()
    svc = issue(api, admin, "svc-a", ["job.submit", "job.submit_on_behalf"])
    job_id = api.client.post("/v1/jobs", json=submit_body(on_behalf_of="u2"), headers=H(svc)).json()["job_id"]
    u2 = api.member("u2")
    cancelled = api.client.post(f"/v1/jobs/{job_id}/cancel", json={}, headers=H(u2))
    assert cancelled.status_code == 200


def test_credentials_are_listed_without_values_and_need_the_manage_permission() -> None:
    api = build_api()
    admin = api.admin()
    token = issue(api, admin, "svc-a", ["job.general"])
    listed = api.client.get("/v1/service-credentials", headers=H(admin))
    assert listed.status_code == 200 and listed.json()[0]["name"] == "svc-a"
    assert token not in listed.text and "token" not in listed.json()[0]
    for call in (
        lambda t: api.client.get("/v1/service-credentials", headers=H(t)),
        lambda t: api.client.post("/v1/service-credentials", json={"name": "x", "permissions": []}, headers=H(t)),
        lambda t: api.client.delete("/v1/service-credentials/anything", headers=H(t)),
    ):
        response = call(api.member("alice"))
        assert response.status_code == 403 and response.json()["required_permissions"] == ["access.manage"]
    denied = [
        r for r in api.client.get("/v1/audit-log", params={"outcome": "denied"}, headers=H(admin)).json()["items"]
    ]
    assert len([r for r in denied if r["operation"].startswith("service_credential")]) == 3


def test_service_token_cannot_reach_management_even_with_manage_requested() -> None:
    api = build_api()
    admin = api.admin()
    response = api.client.post(
        "/v1/service-credentials", json={"name": "svc-x", "permissions": ["access.manage"]}, headers=H(admin)
    )
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"
    assert response.json()["field"] == "permissions"
    duplicate_first = api.client.post(
        "/v1/service-credentials", json={"name": "dup", "permissions": []}, headers=H(admin)
    )
    assert duplicate_first.status_code == 201
    duplicate = api.client.post("/v1/service-credentials", json={"name": "dup", "permissions": []}, headers=H(admin))
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "duplicate_credential_name"
