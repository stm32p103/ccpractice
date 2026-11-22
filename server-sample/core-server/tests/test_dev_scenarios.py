"""quickstart.md §3 の手で確かめるシナリオのうち、設定ファイルと実際の起動に依るもの(dev のメモリ構成)。

- 手順 8: アクセス設定の TOML を書き換えて `POST /v1/access/reload`。次の呼び出しから新しい権限。不正な設定は
  `400 access_config_invalid` で、現在の対応表が保たれる。
- 手順 10: `allowed_networks` から接続元を外すと `403 network_not_allowed`。
- 手順 4・5: 代理提出と失効(設定の上限・実時計・乱数の識別子での通し)。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from job_core_server.settings import load_settings
from job_core_server.wiring import build_app

CONFIG = Path(__file__).resolve().parents[1] / "config"


def prepared(tmp_path: Path, allowed: str = '["127.0.0.0/8"]') -> tuple[Path, Path]:
    access = tmp_path / "access.dev.toml"
    shutil.copy(CONFIG / "access.dev.toml", access)
    server = tmp_path / "server.dev.toml"
    text = (CONFIG / "server.dev.toml").read_text(encoding="utf-8")
    server.write_text(text.replace('allowed_networks = ["127.0.0.0/8", "::1/128"]', f"allowed_networks = {allowed}"))
    return server, access


def client_of(server: Path) -> TestClient:
    return TestClient(build_app(load_settings(server)), client=("127.0.0.1", 50000))


def login(c: TestClient, subject: str, groups: str) -> dict[str, str]:
    body = {"proof": {"subject": subject, "groups": groups}, "delivery": "token"}
    return {"Authorization": f"Bearer {c.post('/v1/auth/login', json=body).json()['session_token']}"}


def test_step_8_access_file_change_applies_after_reload_and_invalid_files_are_rejected(tmp_path: Path) -> None:
    server, access = prepared(tmp_path)
    c = client_of(server)
    admin, member = login(c, "root", "g-admin"), login(c, "u1", "g-member")
    assert "job.submit" in c.get("/v1/auth/session", headers=member).json()["permissions"]
    access.write_text(access.read_text(encoding="utf-8").replace('"g-member" = ["member"]', '"g-member" = ["viewer"]'))
    reloaded = c.post("/v1/access/reload", headers=admin)
    assert reloaded.status_code == 200 and reloaded.json()["changed"] is True
    assert "job.submit" not in c.get("/v1/auth/session", headers=member).json()["permissions"]
    digest = c.get("/v1/access/mapping", headers=admin).json()["digest"]
    access.write_text(access.read_text(encoding="utf-8").replace('"g-member" = ["viewer"]', '"g-member" = ["nope"]'))
    rejected = c.post("/v1/access/reload", headers=admin)
    assert rejected.status_code == 400 and rejected.json()["code"] == "access_config_invalid"
    assert c.get("/v1/access/mapping", headers=admin).json()["digest"] == digest  # 現在の対応表が保たれる
    access.write_text("not = = toml")
    assert c.post("/v1/access/reload", headers=admin).status_code == 400


def test_step_10_a_source_outside_allowed_networks_is_refused(tmp_path: Path) -> None:
    server, _ = prepared(tmp_path, allowed='["203.0.113.0/24"]')
    c = client_of(server)
    response = c.get("/healthz")
    assert response.status_code == 403 and response.json()["code"] == "network_not_allowed"


def test_steps_4_and_5_delegation_and_revocation_with_real_clock_and_random_ids(tmp_path: Path) -> None:
    server, _ = prepared(tmp_path)
    c = client_of(server)
    admin = login(c, "root", "g-admin")
    c.put("/v1/capability-allowlist", json={"entries": {"k1": "single"}}, headers=admin)
    runner = c.post("/v1/runners", json={"name": "r-a"}, headers=admin).json()["token"]["token"]
    c.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers={"Authorization": f"Bearer {runner}"})
    issued = c.post(
        "/v1/service-credentials",
        json={"name": "svc-a", "permissions": ["job.submit", "job.submit_on_behalf"]},
        headers=admin,
    ).json()
    svc = {"Authorization": f"Bearer {issued['token']}"}
    body = {
        "definition": {
            "job_type": "t1",
            "requirement": {"all": [{"key": "k1", "op": "eq", "value": "v"}]},
            "payload": {"n": 1},
            "timeout_seconds": 60,
        },
        "on_behalf_of": "u2",
    }
    assert c.post("/v1/jobs", json=body, headers=svc).status_code == 201
    assert c.post("/v1/jobs", json=body, headers=login(c, "u3", "g-member")).status_code == 403
    log = c.get("/v1/audit-log", params={"operation": "submit"}, headers=admin).json()["items"]
    assert log[0]["on_behalf_of"] == "u2" and log[0]["actor"].startswith("svc:")
    assert c.delete(f"/v1/service-credentials/{issued['credential_id']}", headers=admin).status_code == 204
    assert c.post("/v1/jobs", json=body, headers=svc).status_code == 401
