"""US3-1〜4: ランナーが自身の認証情報で、ランナー用の操作だけを自身に関する対象に限って行う(spec US3)。"""

from __future__ import annotations

from datetime import timedelta

from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def setup() -> tuple[ApiFixture, str, str, str]:
    api = build_api()
    admin = api.admin()
    created = api.client.post("/v1/runners", json={"name": "r-a"}, headers=H(admin)).json()
    api.client.put("/v1/capability-allowlist", json={"entries": {"k1": "single"}}, headers=H(admin))
    return api, admin, created["runner_id"], created["token"]["token"]


def test_us3_1_full_runner_round_trip() -> None:
    api, admin, runner_id, token = setup()
    alice = api.member("alice")
    registered = api.client.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=H(token))
    assert registered.status_code == 200 and registered.json()["state"] == "online"
    assert registered.json()["heartbeat_interval_seconds"] > 0
    assert api.client.post("/v1/runner/heartbeat", headers=H(token)).status_code == 200

    nothing = api.client.post("/v1/runner/job-requests", headers=H(token))
    assert nothing.status_code == 200 and nothing.json()["assignment"] is None
    assert nothing.json()["not_assigned_reason"]["kind"] == "no_matching_job"

    job_id = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    assigned = api.client.post("/v1/runner/job-requests", headers=H(token))
    assignment = assigned.json()["assignment"]
    assert assigned.status_code == 200 and assignment["job_id"] == job_id
    assert assignment["definition"]["payload"] == {"n": 1} and assignment["lease_id"]
    running = api.client.get(f"/v1/runners/{runner_id}", headers=H(admin)).json()
    assert running["running_job_id"] == job_id

    fault = api.client.post("/v1/runner/fault", json={"description": "disk full"}, headers=H(token))
    assert fault.status_code == 200 and fault.json()["state"] == "fault"
    recovered = api.client.delete("/v1/runner/fault", headers=H(token))
    assert recovered.status_code == 200 and recovered.json()["state"] == "online"

    finished = api.client.post(
        f"/v1/runner/jobs/{job_id}/result", json={"outcome": "succeeded", "result_summary": "ok"}, headers=H(token)
    )
    assert finished.status_code == 200 and finished.json()["state"] == "succeeded"
    assert api.client.get(f"/v1/jobs/{job_id}", headers=H(alice)).json()["summary"]["state"] == "succeeded"


def test_us3_1_abort_flow_stopped_confirmation() -> None:
    api, _admin, _runner_id, token = setup()
    alice, op = api.member("alice"), api.operator("op")
    api.client.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=H(token))
    job_id = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    api.client.post("/v1/runner/job-requests", headers=H(token))
    api.client.post(f"/v1/jobs/{job_id}/cancel", json={"reason": "stop"}, headers=H(op))
    stopped = api.client.post(f"/v1/runner/jobs/{job_id}/stopped", headers=H(token))
    assert stopped.status_code == 200 and stopped.json()["state"] == "cancelled"


def test_us3_2_revoked_token_is_unauthorized_and_gets_no_job() -> None:
    api, admin, runner_id, token = setup()
    alice = api.member("alice")
    api.client.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=H(token))
    api.client.post("/v1/jobs", json=submit_body(), headers=H(alice))
    assert api.client.delete(f"/v1/runners/{runner_id}/token", headers=H(admin)).status_code == 204
    response = api.client.post("/v1/runner/job-requests", headers=H(token))
    assert response.status_code == 401 and response.json()["code"] == "authentication_failed"
    assert api.queue_order() != []


def test_us3_3_runner_token_cannot_use_user_operations() -> None:
    api, _admin, _runner_id, token = setup()
    other_id, _ = api.register_runner("r-b")
    alice = api.member("alice")
    j1 = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    j2 = api.client.post("/v1/jobs", json=submit_body(definition_payload={"n": 2}), headers=H(alice)).json()["job_id"]
    cases = [
        api.client.post("/v1/jobs", json=submit_body(), headers=H(token)),
        api.client.post(
            f"/v1/jobs/{j1}/reschedule", json={"placement": {"anchor_job_id": j2, "side": "before"}}, headers=H(token)
        ),
        api.client.post("/v1/runners", json={"name": "r-evil"}, headers=H(token)),
        api.client.put(f"/v1/runners/{other_id}/maintenance", json={}, headers=H(token)),
        api.client.get("/v1/audit-log", headers=H(token)),
        api.client.post("/v1/service-credentials", json={"name": "x", "permissions": []}, headers=H(token)),
    ]
    assert [c.status_code for c in cases] == [403] * len(cases)


def test_us3_4_no_runner_id_in_urls_so_other_runners_cannot_be_targeted() -> None:
    api, _admin, _runner_id, token = setup()
    _other_id, other_token = api.register_runner("r-b")
    spec_paths = api.app.openapi()["paths"]
    runner_paths = [p for p in spec_paths if p.startswith("/v1/runner/")]
    assert runner_paths and all("runner_id" not in p for p in runner_paths)
    api.client.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=H(token))
    alice = api.member("alice")
    job_id = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    api.client.post("/v1/runner/job-requests", headers=H(token))
    # 別のランナー(r-b)のトークンで、r-a に割り当てられたジョブの終了を報告しても受け付けられない
    wrong = api.client.post(f"/v1/runner/jobs/{job_id}/result", json={"outcome": "succeeded"}, headers=H(other_token))
    assert wrong.status_code == 403 and wrong.json()["code"] == "runner_mismatch"
    still_running = api.client.get(f"/v1/jobs/{job_id}", headers=H(alice)).json()["summary"]["state"]
    assert still_running == "running"
    denied = api.client.get("/v1/audit-log", params={"outcome": "denied"}, headers=H(api.admin())).json()["items"]
    assert any(r["denial_code"] == "runner_mismatch" for r in denied)


def test_users_and_services_cannot_call_runner_endpoints() -> None:
    api, _admin, _runner_id, _token = setup()
    service = api.issue_service_token(["job.submit", "job.general"])
    for caller in (api.admin(), api.member("alice"), service):
        for method, path, body in (
            ("post", "/v1/runner/registration", {"capabilities": {"k1": "v"}}),
            ("post", "/v1/runner/heartbeat", None),
            ("post", "/v1/runner/job-requests", None),
        ):
            response = api.client.request(method, path, json=body, headers=H(caller))
            assert response.status_code == 403, (path, response.text)
            assert response.json()["code"] == "permission_denied"


def test_invalid_declaration_reports_keys_and_reasons_only() -> None:
    api, _admin, _runner_id, token = setup()
    response = api.client.post(
        "/v1/runner/registration", json={"capabilities": {"not-allowed": "SECRET-CAPABILITY-VALUE"}}, headers=H(token)
    )
    assert response.status_code == 422 and response.json()["code"] == "invalid_declaration"
    assert "SECRET-CAPABILITY-VALUE" not in response.text
    assert response.json()["violations"][0]["key"] == "not-allowed"


def test_lease_expiry_via_heartbeat_gap_is_observable_through_the_api() -> None:
    api, admin, runner_id, token = setup()
    api.client.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=H(token))
    api.advance(timedelta(hours=1))
    detail = api.client.get(f"/v1/runners/{runner_id}", headers=H(admin)).json()
    assert detail["state"] == "offline"
