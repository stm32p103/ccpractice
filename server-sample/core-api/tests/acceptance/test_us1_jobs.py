"""US1-1〜4: ジョブの提出・参照・スケジュール変更・取り消し・強制中断・やり直し(spec US1)。"""

from __future__ import annotations

from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def setup() -> tuple[ApiFixture, str, str, str]:
    api = build_api()
    api.register_runner()
    return api, api.member("alice"), api.operator("op"), api.admin("admin")


def submit(api: ApiFixture, token: str, **overrides: object) -> str:
    body = submit_body(**overrides)
    # 重複(同じ内容の待機中)を避けるため、payload を変える
    body["definition"]["payload"] = {"n": api._counter}
    api._counter += 1
    response = api.client.post("/v1/jobs", json=body, headers=H(token))
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def test_us1_1_submit_returns_201_location_and_is_readable() -> None:
    api, alice, _, _ = setup()
    response = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice))
    assert response.status_code == 201
    body = response.json()
    assert body["position"] == 1
    assert response.headers["location"] == f"/v1/jobs/{body['job_id']}"
    detail = api.client.get(response.headers["location"], headers=H(alice))
    assert detail.status_code == 200
    summary = detail.json()["summary"]
    assert summary["state"] == "queued" and summary["owner"] == "alice" and summary["position"] == 1
    assert detail.json()["definition"]["payload"] == {"n": 1}
    history = api.client.get(f"/v1/jobs/{body['job_id']}/history", headers=H(alice))
    assert history.status_code == 200 and [r["operation"] for r in history.json()] == ["submit"]


def test_us1_1_submit_without_permission_is_403_and_denied_is_audited() -> None:
    api, _, _, admin = setup()
    viewer = api.viewer("v1")
    response = api.client.post("/v1/jobs", json=submit_body(), headers=H(viewer))
    assert response.status_code == 403 and response.json()["code"] == "permission_denied"
    assert "job.submit" in response.json()["required_permissions"]
    log = api.client.get("/v1/audit-log", params={"outcome": "denied", "actor": "v1"}, headers=H(admin))
    assert log.status_code == 200 and log.json()["items"][0]["denial_code"] == "permission_denied"


def test_us1_2_placement_and_reschedule_change_queue_order_but_not_running_jobs() -> None:
    api, alice, op, _ = setup()
    j1 = submit(api, alice)
    j2 = submit(api, alice)
    j3 = submit(api, alice)
    placed = api.client.post(
        "/v1/jobs",
        json=submit_body(placement={"anchor_job_id": j1, "side": "before"}, definition_payload={"n": 99}),
        headers=H(op),
    )
    assert placed.status_code == 201 and placed.json()["position"] == 1
    # 位置指定にはスケジュールの権限が要る(一般の利用者は拒否)
    denied = api.client.post(
        "/v1/jobs",
        json=submit_body(placement={"anchor_job_id": j1, "side": "after"}, definition_payload={"n": 98}),
        headers=H(alice),
    )
    assert denied.status_code == 403
    moved = api.client.post(
        f"/v1/jobs/{j3}/reschedule", json={"placement": {"anchor_job_id": j1, "side": "before"}}, headers=H(op)
    )
    assert moved.status_code == 200 and moved.json()["position_after"] < moved.json()["position_before"]
    order = api.queue_order()
    assert order.index(j3) < order.index(j1) < order.index(j2)
    # 実行中のジョブはスケジュール変更の対象にならない
    runner_id, runner_token = api.register_runner("r-b")
    running_id = api.assign_next(runner_id, runner_token)
    assert running_id is not None
    again = api.client.post(
        f"/v1/jobs/{running_id}/reschedule", json={"placement": {"anchor_job_id": j2, "side": "after"}}, headers=H(op)
    )
    assert again.status_code == 409 and again.json()["code"] == "target_not_queued"
    api.client.get(f"/v1/jobs/{running_id}", headers=H(alice))


def test_us1_3_cancel_queued_and_force_abort_running_requires_reason() -> None:
    api, alice, op, _ = setup()
    queued = submit(api, alice)
    cancelled = api.client.post(f"/v1/jobs/{queued}/cancel", json={}, headers=H(alice))
    assert cancelled.status_code == 200
    assert cancelled.json()["abort_pending"] is False and cancelled.json()["state"] != "queued"

    running_job = submit(api, alice)
    runner_id, runner = api.register_runner("r-b")
    assert api.assign_next(runner_id, runner) == running_job
    no_reason = api.client.post(f"/v1/jobs/{running_job}/cancel", json={}, headers=H(op))
    assert no_reason.status_code == 422 and no_reason.json()["code"] == "reason_required"
    aborted = api.client.post(f"/v1/jobs/{running_job}/cancel", json={"reason": "stop it"}, headers=H(op))
    assert aborted.status_code == 200 and aborted.json()["abort_pending"] is True
    twice = api.client.post(f"/v1/jobs/{running_job}/cancel", json={"reason": "again"}, headers=H(op))
    assert twice.status_code == 409 and twice.json()["code"] == "abort_already_requested"


def test_us1_3_other_users_job_needs_the_right_permission() -> None:
    api, alice, _, _ = setup()
    bob = api.member("bob")
    job = submit(api, alice)
    denied = api.client.post(f"/v1/jobs/{job}/cancel", json={}, headers=H(bob))
    assert denied.status_code == 403
    assert "job.cancel_queued" in denied.json()["required_permissions"]


def test_us1_4_retry_creates_a_new_job_with_a_link_to_the_original() -> None:
    api, alice, _, _ = setup()
    job = submit(api, alice)
    api.client.post(f"/v1/jobs/{job}/cancel", json={}, headers=H(alice))
    retried = api.client.post(f"/v1/jobs/{job}/retry", json={}, headers=H(alice))
    assert retried.status_code == 201
    new_id = retried.json()["job_id"]
    assert new_id != job and retried.headers["location"] == f"/v1/jobs/{new_id}"
    detail = api.client.get(f"/v1/jobs/{new_id}", headers=H(alice)).json()
    assert detail["retry_of"]["job_id"] == job and detail["summary"]["retry_of"] == job
    original = api.client.get(f"/v1/jobs/{job}", headers=H(alice)).json()
    assert original["retries"] == [new_id]


def test_us1_4_retry_of_a_queued_job_is_an_invalid_state_transition() -> None:
    api, alice, _, _ = setup()
    job = submit(api, alice)
    response = api.client.post(f"/v1/jobs/{job}/retry", json={}, headers=H(alice))
    assert response.status_code == 409 and response.json()["code"] == "invalid_state_transition"


def test_unknown_job_is_404_and_validation_errors_do_not_echo_values() -> None:
    api, alice, _, _ = setup()
    assert api.client.get("/v1/jobs/nope", headers=H(alice)).json()["code"] == "job_not_found"
    bad = api.client.post(
        "/v1/jobs",
        json={"definition": {"requirement": 1, "payload": 1, "timeout_seconds": "SECRET-VALUE"}},
        headers=H(alice),
    )
    assert bad.status_code == 400 and bad.json()["code"] == "request_invalid"
    assert "SECRET-VALUE" not in bad.text
