"""US9-1〜4: 状態を変える呼び出しをすべて監査ログに残す(spec US9。FR-020、FR-021)。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def audit(api: ApiFixture, **params: Any) -> list[dict[str, Any]]:
    response = api.client.get("/v1/audit-log", params={"limit": 200, **params}, headers=H(api.admin("auditor")))
    assert response.status_code == 200
    return response.json()["items"]  # type: ignore[no-any-return]


def test_us9_1_successful_changes_record_actor_time_target_and_operation() -> None:
    api = build_api()
    api.register_runner()
    alice, op = api.member("alice"), api.operator("op")
    job = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    other = api.client.post("/v1/jobs", json=submit_body(definition_payload={"n": 2}), headers=H(alice)).json()[
        "job_id"
    ]
    api.client.post(
        f"/v1/jobs/{other}/reschedule", json={"placement": {"anchor_job_id": job, "side": "before"}}, headers=H(op)
    )
    api.client.post(f"/v1/jobs/{job}/cancel", json={}, headers=H(alice))
    records = {r["operation"]: r for r in audit(api, outcome="succeeded") if r["job_id"] in {job, other}}
    for operation, actor, kind in (
        ("submit", "alice", "human"),
        ("reschedule", "op", "human"),
        ("cancel_queued", "alice", "human"),
    ):
        record = records[operation]
        assert record["actor"] == actor and record["actor_kind"] == kind
        assert record["occurred_at"] and record["job_id"] in {job, other} and record["outcome"] == "succeeded"


def test_us9_2_on_behalf_records_both_the_nominal_submitter_and_the_agent() -> None:
    api = build_api()
    api.register_runner()
    svc = api.issue_service_token(["job.submit", "job.submit_on_behalf"])
    job = api.client.post("/v1/jobs", json=submit_body(on_behalf_of="u2"), headers=H(svc)).json()["job_id"]
    [record] = [r for r in audit(api, job_id=job) if r["operation"] == "submit"]
    assert record["on_behalf_of"] == "u2" and record["actor"].startswith("svc:") and record["actor_kind"] == "service"


def test_us9_3_permission_denials_record_the_fact_and_the_subject() -> None:
    api = build_api()
    api.register_runner()
    viewer = api.viewer("v1")
    assert api.client.post("/v1/jobs", json=submit_body(), headers=H(viewer)).status_code == 403
    assert api.client.post("/v1/runners", json={"name": "x"}, headers=H(viewer)).status_code == 403
    assert (
        api.client.post("/v1/service-credentials", json={"name": "x", "permissions": []}, headers=H(viewer)).status_code
        == 403
    )
    denied = [r for r in audit(api, outcome="denied", actor="v1")]
    assert {r["operation"] for r in denied} >= {"submit", "runner_create", "service_credential_issue"}
    assert all(r["denial_code"] == "permission_denied" and r["denial_required"] for r in denied)


def test_us9_4_authentication_failures_are_recorded_without_credential_values() -> None:
    api = build_api()
    secret_token = "ss_THIS-IS-A-FAKE-SECRET-VALUE"
    for _ in range(3):
        api.client.get("/v1/queue", headers=H(secret_token))
    api.client.get("/v1/queue", headers=H("rt_ANOTHER-FAKE-SECRET"))
    failures = audit(api, operation="auth_failed")
    assert failures and all(r["actor"] == "unauthenticated" and r["actor_kind"] == "anonymous" for r in failures)
    assert all(r["outcome"] == "denied" and r["denial_code"] == "authentication_failed" for r in failures)
    text = str(failures) + str(audit(api, operation="runner_authenticate"))
    assert "FAKE-SECRET" not in text
    assert len([r for r in failures if r["after"].get("kind") == "session"]) == 1  # 窓で抑制される


def test_login_logout_credentials_and_mapping_changes_are_recorded() -> None:
    api = build_api()
    admin = api.admin("root")
    login = api.client.post(
        "/v1/auth/login", json={"proof": {"subject": "u1", "groups": "g-admin"}, "delivery": "token"}
    )
    token = login.json()["session_token"]
    api.client.delete("/v1/auth/session", headers=H(token))
    issued = api.client.post(
        "/v1/service-credentials", json={"name": "svc", "permissions": ["job.general"]}, headers=H(admin)
    )
    api.client.delete(f"/v1/service-credentials/{issued.json()['credential_id']}", headers=H(admin))
    import copy

    from job_core_api.access.config import AccessConfig
    from job_testing.api_fakes import DEFAULT_ACCESS

    changed = copy.deepcopy(DEFAULT_ACCESS)
    changed["default_roles"] = []
    api.access_source.replace(AccessConfig.from_mapping(changed))
    api.client.post("/v1/access/reload", headers=H(admin))
    operations = [r["operation"] for r in audit(api, outcome="succeeded")]
    for expected in (
        "login",
        "logout",
        "service_credential_issue",
        "service_credential_revoke",
        "access_config_change",
    ):
        assert expected in operations, expected
    text = str(audit(api))
    assert token not in text and issued.json()["token"] not in text


def test_audit_records_are_append_only_through_the_api() -> None:
    api = build_api()
    paths = api.app.openapi()["paths"]
    assert set(paths["/v1/audit-log"]) == {"get"}
    api.advance(timedelta(seconds=1))
