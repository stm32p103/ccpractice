"""実 DB での通しの試験(FakeIdentityProvider + PostgreSQL。quickstart §4 の 2〜4 に相当)。

提出 → ランナーの取得 → 終了 → やり直し。サービスの再起動(アプリの作り直し)後も、セッション・認証情報・ジョブが残る。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from job_core_persistence import make_engine, migrate
from job_core_persistence.models import metadata
from job_core_server.settings import load_settings
from job_core_server.wiring import build_app

pytestmark = pytest.mark.postgres
CONFIG = Path(__file__).resolve().parents[1] / "config"
BODY = {
    "definition": {
        "job_type": "t1",
        "requirement": {"all": [{"key": "k1", "op": "eq", "value": "v"}]},
        "payload": {"n": 1},
        "timeout_seconds": 60,
    }
}


@pytest.fixture
def server_file(tmp_path: Path, pg_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    migrate(pg_dsn)
    engine = make_engine(pg_dsn)
    with engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE " + ", ".join(t.name for t in metadata.sorted_tables) + " RESTART IDENTITY"))
    engine.dispose()
    monkeypatch.setenv("JOB_TEST_DATABASE_URL", pg_dsn)
    shutil.copy(CONFIG / "access.dev.toml", tmp_path / "access.dev.toml")
    text = (CONFIG / "server.dev.toml").read_text(encoding="utf-8")
    text = text.replace('kind = "memory"', 'kind = "postgres"\ndsn_secret = "JOB_TEST_DATABASE_URL"')
    path = tmp_path / "server.dev.toml"
    path.write_text(text, encoding="utf-8")
    return path


def client(server_file: Path) -> TestClient:
    return TestClient(build_app(load_settings(server_file)), client=("127.0.0.1", 50000))


def login(c: TestClient, subject: str, groups: str) -> str:
    body = {"proof": {"subject": subject, "groups": groups}, "delivery": "token"}
    return c.post("/v1/auth/login", json=body).json()["session_token"]


def test_round_trip_and_state_survives_a_restart(server_file: Path) -> None:
    c = client(server_file)
    admin_token = login(c, "root", "g-admin")
    admin = {"Authorization": f"Bearer {admin_token}"}
    c.put("/v1/capability-allowlist", json={"entries": {"k1": "single"}}, headers=admin)
    created = c.post("/v1/runners", json={"name": "r-a"}, headers=admin).json()
    runner = {"Authorization": f"Bearer {created['token']['token']}"}
    assert c.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=runner).status_code == 200
    credential = c.post("/v1/service-credentials", json={"name": "svc", "permissions": ["job.general"]}, headers=admin)
    service = {"Authorization": f"Bearer {credential.json()['token']}"}

    job = c.post("/v1/jobs", json=BODY, headers=admin).json()["job_id"]
    assigned = c.post("/v1/runner/job-requests", headers=runner).json()["assignment"]
    assert assigned["job_id"] == job
    done = c.post(f"/v1/runner/jobs/{job}/result", json={"outcome": "failed", "result_summary": "x"}, headers=runner)
    assert done.json()["state"] == "failed"
    retried = c.post(f"/v1/jobs/{job}/retry", json={}, headers=admin)
    assert retried.status_code == 201
    new_job = retried.json()["job_id"]

    restarted = client(server_file)  # サービスの再起動(アプリの作り直し)
    assert restarted.get("/v1/auth/session", headers=admin).status_code == 200  # セッションが残る
    assert restarted.get("/v1/queue", headers=service).json()["items"][0]["job_id"] == new_job  # 認証情報・ジョブが残る
    detail = restarted.get(f"/v1/jobs/{job}", headers=admin).json()
    assert detail["summary"]["state"] == "failed" and detail["retries"] == [new_job]
    assert restarted.post("/v1/runner/job-requests", headers=runner).json()["assignment"]["job_id"] == new_job
    ops = {r["operation"] for r in restarted.get("/v1/audit-log", params={"limit": 200}, headers=admin).json()["items"]}
    assert {"submit", "assign", "complete", "retry", "runner_create", "service_credential_issue", "login"} <= ops


def test_revoked_credentials_stay_revoked_after_a_restart(server_file: Path) -> None:
    c = client(server_file)
    admin = {"Authorization": f"Bearer {login(c, 'root', 'g-admin')}"}
    issued = c.post(
        "/v1/service-credentials", json={"name": "svc", "permissions": ["job.general"]}, headers=admin
    ).json()
    service = {"Authorization": f"Bearer {issued['token']}"}
    assert c.get("/v1/queue", headers=service).status_code == 200
    c.delete(f"/v1/service-credentials/{issued['credential_id']}", headers=admin)
    restarted = client(server_file)
    assert restarted.get("/v1/queue", headers=service).status_code == 401
