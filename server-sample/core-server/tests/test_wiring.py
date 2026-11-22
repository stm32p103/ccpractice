"""組み立ての検査(dev のメモリ構成で、実際に API が動くこと)。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from job_core_server.settings import load_settings
from job_core_server.wiring import api_settings_of, build_app

CONFIG = Path(__file__).resolve().parents[1] / "config"


def client() -> TestClient:
    app = build_app(load_settings(CONFIG / "server.dev.toml"))
    return TestClient(app, client=("127.0.0.1", 50000))


def test_dev_server_serves_healthz_and_the_openapi_requires_authentication() -> None:
    c = client()
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/openapi.json").status_code == 401


def test_login_with_the_fake_provider_derives_permissions_from_the_access_file() -> None:
    c = client()
    response = c.post("/v1/auth/login", json={"proof": {"subject": "u1", "groups": "g-admin"}, "delivery": "token"})
    assert response.status_code == 200
    assert "access.manage" in response.json()["permissions"]
    token = response.json()["session_token"]
    assert c.get("/v1/queue", headers={"Authorization": f"Bearer {token}"}).json() == {"items": []}


def test_a_job_round_trip_works_with_real_clock_and_random_ids() -> None:
    c = client()
    admin = c.post("/v1/auth/login", json={"proof": {"subject": "root", "groups": "g-admin"}, "delivery": "token"})
    auth = {"Authorization": f"Bearer {admin.json()['session_token']}"}
    c.put("/v1/capability-allowlist", json={"entries": {"k1": "single"}}, headers=auth)
    created = c.post("/v1/runners", json={"name": "r-a"}, headers=auth).json()
    runner = {"Authorization": f"Bearer {created['token']['token']}"}
    assert c.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=runner).status_code == 200
    body = {
        "definition": {
            "job_type": "t1",
            "requirement": {"all": [{"key": "k1", "op": "eq", "value": "v"}]},
            "payload": {"n": 1},
            "timeout_seconds": 60,
        }
    }
    job = c.post("/v1/jobs", json=body, headers=auth)
    assert job.status_code == 201 and len(job.json()["job_id"]) == 32  # 乱数の識別子
    assigned = c.post("/v1/runner/job-requests", headers=runner).json()["assignment"]
    assert assigned["job_id"] == job.json()["job_id"]
    done = c.post(f"/v1/runner/jobs/{assigned['job_id']}/result", json={"outcome": "succeeded"}, headers=runner)
    assert done.json()["state"] == "succeeded"


def test_api_settings_follow_the_server_settings() -> None:
    settings = load_settings(CONFIG / "server.dev.toml")
    api = api_settings_of(settings)
    assert api.cookie_secure is False and api.cookie_name == "session"
    assert api.allowed_networks == ("127.0.0.0/8", "::1/128")
