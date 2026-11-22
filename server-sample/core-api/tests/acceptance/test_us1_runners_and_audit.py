"""US1: ランナーの管理と監査ログ(spec US1、contracts/http-api.md §2.3・§2.4)。"""

from __future__ import annotations

from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def test_runner_lifecycle_token_is_shown_once_and_never_listed() -> None:
    api = build_api()
    admin = api.admin()
    created = api.client.post("/v1/runners", json={"name": "r-a"}, headers=H(admin))
    assert created.status_code == 201
    body = created.json()
    runner_id, token = body["runner_id"], body["token"]["token"]
    assert token.startswith("rt_") and created.headers["location"] == f"/v1/runners/{runner_id}"

    for path in (f"/v1/runners/{runner_id}", "/v1/runners", f"/v1/runners/{runner_id}/history", "/v1/audit-log"):
        text = api.client.get(path, headers=H(admin)).text
        assert token not in text, path

    listed = api.client.get("/v1/runners", headers=H(admin)).json()
    assert [r["name"] for r in listed] == ["r-a"] and "token" not in listed[0]
    detail = api.client.get(f"/v1/runners/{runner_id}", headers=H(admin)).json()
    assert detail["state"] in {"offline", "online"} and detail["running_job_id"] is None

    reissued = api.client.post(f"/v1/runners/{runner_id}/token", headers=H(admin))
    assert reissued.status_code == 200 and reissued.json()["token"] != token
    assert api.client.get("/v1/runners", headers=H(token)).status_code == 401  # 旧トークンは失効

    revoked = api.client.delete(f"/v1/runners/{runner_id}/token", headers=H(admin))
    assert revoked.status_code == 204
    assert api.client.get("/v1/runners", headers=H(reissued.json()["token"])).status_code == 401


def test_maintenance_fault_and_delete() -> None:
    api = build_api()
    admin = api.admin()
    runner_id, _ = api.register_runner("r-a")
    maintenance = api.client.put(f"/v1/runners/{runner_id}/maintenance", json={"reason": "disk"}, headers=H(admin))
    assert maintenance.status_code == 200 and maintenance.json()["state"] == "maintenance"
    again = api.client.put(f"/v1/runners/{runner_id}/maintenance", json={}, headers=H(admin))
    assert again.status_code == 409 and again.json()["code"] == "already_in_maintenance"
    cleared = api.client.delete(f"/v1/runners/{runner_id}/maintenance", headers=H(admin))
    assert cleared.status_code == 200 and cleared.json()["state"] != "maintenance"
    assert api.client.delete(f"/v1/runners/{runner_id}", headers=H(admin)).status_code == 204
    assert api.client.get(f"/v1/runners/{runner_id}", headers=H(admin)).status_code == 404


def test_delete_runner_with_unfinished_job_is_refused() -> None:
    api = build_api()
    admin, alice = api.admin(), api.member()
    runner_id, token = api.register_runner("r-a")
    api.client.post("/v1/jobs", json=submit_body(), headers=H(alice))
    assert api.assign_next(runner_id, token) is not None
    response = api.client.delete(f"/v1/runners/{runner_id}", headers=H(admin))
    assert response.status_code == 409 and response.json()["code"] == "runner_has_unfinished_job"
    assert "job_id" in response.json()


def test_allowlist_get_and_replace() -> None:
    api = build_api()
    admin, viewer = api.admin(), api.viewer()
    put = api.client.put(
        "/v1/capability-allowlist",
        json={"entries": {"k1": "single", "set1": "set"}, "reason": "init"},
        headers=H(admin),
    )
    assert put.status_code == 200 and put.json()["entries"] == {"k1": "single", "set1": "set"}
    assert api.client.get("/v1/capability-allowlist", headers=H(viewer)).json()["entries"]["set1"] == "set"
    denied = api.client.put("/v1/capability-allowlist", json={"entries": {}}, headers=H(viewer))
    assert denied.status_code == 403
    bad = api.client.put("/v1/capability-allowlist", json={"entries": {"Bad Key": "single"}}, headers=H(admin))
    assert bad.status_code == 422 and bad.json()["code"] == "validation_failed"


def test_runner_management_requires_the_manage_permission() -> None:
    api = build_api()
    member = api.member()
    runner_id, _ = api.register_runner("r-a")
    assert api.client.post("/v1/runners", json={"name": "x"}, headers=H(member)).status_code == 403
    assert api.client.put(f"/v1/runners/{runner_id}/maintenance", json={}, headers=H(member)).status_code == 403
    assert api.client.post(f"/v1/runners/{runner_id}/token", headers=H(member)).status_code == 403
    assert api.client.delete(f"/v1/runners/{runner_id}", headers=H(member)).status_code == 403
    duplicate = api.client.post("/v1/runners", json={"name": "r-a"}, headers=H(api.admin()))
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "duplicate_runner_name"


def test_audit_log_filters_and_requires_audit_permission() -> None:
    api = build_api()
    admin, member = api.admin(), api.member("alice")
    assert api.client.get("/v1/audit-log", headers=H(member)).status_code == 403
    api.client.post("/v1/runners", json={"name": "r-a"}, headers=H(admin))
    api.client.post("/v1/runners", json={"name": "r-b"}, headers=H(member))  # 拒否される
    everything = api.client.get("/v1/audit-log", headers=H(admin)).json()
    operations = {item["operation"] for item in everything["items"]}
    assert {"runner_create", "read_audit_log"} <= operations
    only_denied = api.client.get("/v1/audit-log", params={"outcome": "denied"}, headers=H(admin)).json()["items"]
    assert only_denied and all(item["outcome"] == "denied" for item in only_denied)
    by_actor = api.client.get("/v1/audit-log", params={"actor": "alice"}, headers=H(admin)).json()["items"]
    assert by_actor and all(item["actor"] == "alice" for item in by_actor)
    page = api.client.get("/v1/audit-log", params={"limit": 1}, headers=H(admin)).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    nxt = api.client.get("/v1/audit-log", params={"limit": 1, "cursor": page["next_cursor"]}, headers=H(admin)).json()
    assert nxt["items"][0]["record_id"] != page["items"][0]["record_id"]
    assert api.client.get("/v1/audit-log", params={"limit": 0}, headers=H(admin)).status_code == 400
    assert api.client.get("/v1/audit-log", params={"operation": "nope"}, headers=H(admin)).status_code == 400
