"""US4-1〜5: 認証基盤でログインし、所属グループからロールと権限が決まる(spec US4)。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from job_core_api.access.config import AccessConfig
from job_core_api.settings import ApiSettings
from job_testing.api_fakes import DEFAULT_ACCESS, ApiFixture, build_api
from job_testing.contracts.access_config import variant

H = ApiFixture.headers
TERMS_FILE = Path(__file__).resolve().parents[3] / "core" / "tests" / "architecture" / "forbidden_terms.txt"


def login(api: ApiFixture, subject: str, groups: str, **extra: object) -> dict:  # type: ignore[type-arg]
    body = {"proof": {"subject": subject, "groups": groups}, "delivery": "token", **extra}
    response = api.client.post("/v1/auth/login", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_us4_1_login_derives_permissions_from_groups_and_default_roles() -> None:
    api = build_api()
    info = login(api, "u1", "g-member")
    assert info["principal_kind"] == "human" and info["subject_id"] == "u1"
    assert set(info["permissions"]) == {"job.general", "job.submit"}
    assert info["session_token"].startswith("ss_") and info["expires_at"] and info["idle_expires_at"]
    session = api.client.get("/v1/auth/session", headers=H(info["session_token"])).json()
    assert set(session["permissions"]) == {"job.general", "job.submit"} and session["session_token"] is None
    unmatched = login(api, "u2", "unknown-group")
    assert set(unmatched["permissions"]) == {"job.general"}  # default_roles
    union = login(api, "u3", "g-member,g-operator")
    assert {"queue.schedule", "job.submit"} <= set(union["permissions"])


def test_us4_1_every_login_issues_a_new_value() -> None:
    api = build_api()
    first = login(api, "u1", "g-member")["session_token"]
    second = login(api, "u1", "g-member")["session_token"]
    assert first != second
    assert api.client.get("/v1/auth/session", headers=H(first)).status_code == 200


def test_us4_2_mapping_change_applies_from_next_call_and_is_audited() -> None:
    api = build_api()
    admin = login(api, "root", "g-admin")["session_token"]
    token = login(api, "u1", "g-member")["session_token"]
    before = api.client.get("/v1/auth/session", headers=H(token)).json()["permissions"]
    assert "queue.schedule" in api.client.get("/v1/access/mapping", headers=H(admin)).json()["roles"]["operator"]
    api.access_source.replace(AccessConfig.from_mapping(variant(groups={"g-member": ["viewer"], "g-admin": ["admin"]})))
    reload = api.client.post("/v1/access/reload", headers=H(admin))
    assert reload.status_code == 200 and reload.json()["changed"] is True
    after = api.client.get("/v1/auth/session", headers=H(token)).json()["permissions"]
    assert set(before) == {"job.general", "job.submit"} and set(after) == {"job.general"}
    log = api.client.get("/v1/audit-log", params={"operation": "access_config_change"}, headers=H(admin)).json()[
        "items"
    ]
    assert len(log) == 1 and log[0]["before"]["digest"] != log[0]["after"]["digest"]
    assert "g-member" in log[0]["after"]["diff"]["groups"]["changed"]
    unchanged = api.client.post("/v1/access/reload", headers=H(admin)).json()
    assert unchanged["changed"] is False


def test_us4_2_invalid_config_is_rejected_and_the_current_mapping_is_kept() -> None:
    api = build_api()
    admin = login(api, "root", "g-admin")["session_token"]
    digest = api.client.get("/v1/access/mapping", headers=H(admin)).json()["digest"]
    api.access_source.replace(lambda: AccessConfig.from_mapping(variant(groups={"g": ["no-such-role"]})))
    response = api.client.post("/v1/access/reload", headers=H(admin))
    assert response.status_code == 400 and response.json()["code"] == "access_config_invalid"
    assert response.json()["violations"] and "no-such-role" not in response.text
    assert api.client.get("/v1/access/mapping", headers=H(admin)).json()["digest"] == digest
    assert api.client.get("/v1/auth/session", headers=H(admin)).status_code == 200


def test_us4_3_unverifiable_identity_is_401_and_unavailable_provider_is_503() -> None:
    api = build_api()
    api.identity.accept_unregistered = False
    rejected = api.client.post("/v1/auth/login", json={"proof": {"subject": "stranger"}, "delivery": "token"})
    assert rejected.status_code == 401 and rejected.json()["code"] == "authentication_failed"
    assert "stranger" not in rejected.text
    api.identity.available = False
    unavailable = api.client.post("/v1/auth/login", json={"proof": {"subject": "u1"}})
    assert unavailable.status_code == 503 and unavailable.json()["code"] == "identity_provider_unavailable"
    admin = api.admin()
    failures = api.client.get("/v1/audit-log", params={"operation": "auth_failed"}, headers=H(admin)).json()["items"]
    assert len(failures) == 1 and failures[0]["actor_kind"] == "anonymous"


def test_us4_4_api_definition_and_responses_do_not_name_the_authentication_provider() -> None:
    api = build_api()
    terms = [t.strip().lower() for t in TERMS_FILE.read_text("utf-8").splitlines() if t.strip() and t[0] != "#"]
    spec_text = str(api.app.openapi()).lower()
    info = str(login(api, "u1", "g-member")).lower()
    assert [t for t in terms if t in spec_text or t in info] == []


def test_us4_5_logout_and_admin_bulk_revocation() -> None:
    api = build_api()
    admin = login(api, "root", "g-admin")["session_token"]
    first, second = login(api, "u1", "g-member")["session_token"], login(api, "u1", "g-member")["session_token"]
    assert api.client.delete("/v1/auth/session", headers=H(first)).status_code == 204
    assert api.client.get("/v1/auth/session", headers=H(first)).status_code == 401
    assert api.client.get("/v1/auth/session", headers=H(second)).status_code == 200
    denied = api.client.delete("/v1/access/sessions", params={"subject_id": "u1"}, headers=H(second))
    assert denied.status_code == 403
    assert api.client.delete("/v1/access/sessions", params={"subject_id": "u1"}, headers=H(admin)).status_code == 204
    assert api.client.get("/v1/auth/session", headers=H(second)).status_code == 401
    ops = [r["operation"] for r in api.client.get("/v1/audit-log", headers=H(admin)).json()["items"]]
    assert ops.count("login") == 3 and ops.count("logout") >= 2


def test_non_session_principals_cannot_logout_but_can_read_their_info() -> None:
    api = build_api()
    token = api.issue_service_token(["job.general"])
    assert api.client.delete("/v1/auth/session", headers=H(token)).status_code == 400
    info = api.client.get("/v1/auth/session", headers=H(token)).json()
    assert info["principal_kind"] == "service" and info["expires_at"] is None


def test_sessions_expire_by_idle_and_absolute_timeouts() -> None:
    api = build_api()
    token = login(api, "u1", "g-member")["session_token"]
    api.advance(timedelta(hours=2, minutes=1))
    assert api.client.get("/v1/auth/session", headers=H(token)).status_code == 401
    token = login(api, "u1", "g-member")["session_token"]
    for _ in range(8):
        api.advance(timedelta(hours=1, minutes=30))
        if api.client.get("/v1/auth/session", headers=H(token)).status_code == 401:
            break
    else:
        raise AssertionError("絶対期限で失効しなかった")


def test_cookie_delivery_sets_a_strict_http_only_cookie_and_state_changes_check_origin() -> None:
    api = build_api(settings=ApiSettings(cookie_secure=False))
    response = api.client.post("/v1/auth/login", json={"proof": {"subject": "u1", "groups": "g-member"}})
    assert response.status_code == 200 and response.json()["session_token"] is None
    cookie = response.headers["set-cookie"].lower()
    assert "session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert api.client.get("/v1/auth/session").status_code == 200
    no_origin = api.client.delete("/v1/auth/session")
    assert no_origin.status_code == 403 and no_origin.json()["code"] == "origin_not_allowed"
    assert api.client.delete("/v1/auth/session", headers={"Origin": "http://testserver"}).status_code == 204
    assert api.client.get("/v1/auth/session").status_code == 401


def test_secure_cookie_uses_the_host_prefix() -> None:
    api = build_api()
    response = api.client.post("/v1/auth/login", json={"proof": {"subject": "u1", "groups": "g-member"}})
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-session=") and "Secure" in cookie


def test_login_from_a_foreign_origin_is_refused() -> None:
    api = build_api()
    response = api.client.post(
        "/v1/auth/login", json={"proof": {"subject": "u1"}}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403 and response.json()["code"] == "origin_not_allowed"


def test_return_to_must_be_a_same_origin_relative_path() -> None:
    from job_testing.api_fakes import FakeIdentityProvider

    api = build_api()
    api.deps.identity.__class__  # noqa: B018 (Fake であることの確認)
    assert isinstance(api.identity, FakeIdentityProvider)
    api.identity._redirect_url = "https://idp.example/authorize"
    for bad in ("https://evil.example/", "//evil.example", "/\\evil", "relative", "/a\nb", "/" + "x" * 600):
        response = api.client.get("/v1/auth/login", params={"return_to": bad}, follow_redirects=False)
        assert response.status_code == 400 and response.json()["code"] == "return_to_invalid", bad
    ok = api.client.get("/v1/auth/login", params={"return_to": "/jobs?x=1"}, follow_redirects=False)
    assert ok.status_code == 302 and ok.headers["location"] == "https://idp.example/authorize"
    assert api.identity.begun == ["/jobs?x=1"]


def test_callback_creates_the_session_and_redirects_to_the_stored_return_to() -> None:
    api = build_api(settings=ApiSettings(cookie_secure=False))
    api.identity._redirect_url = "https://idp.example/authorize"
    api.client.get("/v1/auth/login", params={"return_to": "/queue"}, follow_redirects=False)
    callback = api.client.get(
        "/v1/auth/callback", params={"subject": "u1", "groups": "g-member"}, follow_redirects=False
    )
    assert callback.status_code == 302 and callback.headers["location"] == "/queue"
    assert api.client.get("/v1/auth/session").json()["subject_id"] == "u1"
    bad = api.client.get("/v1/auth/callback", params={"nothing": "x"}, follow_redirects=False)
    assert bad.status_code == 401


def test_begin_login_is_404_for_direct_proof_only_providers() -> None:
    api = build_api()
    assert api.client.get("/v1/auth/login", follow_redirects=False).status_code == 404


def test_default_access_template_is_what_the_tests_use() -> None:
    assert set(DEFAULT_ACCESS["roles"]) == {"viewer", "member", "operator", "admin", "reader"}
