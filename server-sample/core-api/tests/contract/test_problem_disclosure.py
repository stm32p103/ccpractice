"""開示の検査(FR-014、T-A1、T-A8)。

認証情報・payload・ログ・異常の説明・能力の値・内部の例外の文字列を入力に混ぜて失敗を起こしても、
応答とアクセスログに現れない。未知の例外は `500 internal_error` で詳細なし。
"""

from __future__ import annotations

import logging

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers
SECRETS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=12, max_size=24).map(lambda s: f"SECRET{s}")


def failing_calls(api: ApiFixture, secret: str, tokens: dict[str, str]) -> list[object]:
    """秘密を入力に混ぜて、失敗する呼び出しを行う。"""
    client = api.client
    alice, viewer, admin, runner = tokens["alice"], tokens["viewer"], tokens["admin"], tokens["runner"]
    return [
        # 権限の拒否(payload・source・理由に秘密)
        client.post(
            "/v1/jobs",
            json=submit_body(definition_payload={"x": secret}, definition_source=secret),
            headers=H(viewer),
        ),
        # 検証の失敗(型の誤りに秘密)
        client.post("/v1/jobs", json={"definition": {"payload": secret, "timeout_seconds": secret}}, headers=H(alice)),
        # 規則の違反(名前・理由に秘密)
        client.post("/v1/runners", json={"name": secret * 20}, headers=H(admin)),
        # 要件を満たすランナーがない(要件に秘密)
        client.post(
            "/v1/jobs",
            json=submit_body(definition_requirement={"all": [{"key": "k1", "op": "eq", "value": secret}]}),
            headers=H(alice),
        ),
        # 能力の申告の違反(能力の値に秘密)
        client.post("/v1/runner/registration", json={"capabilities": {"nokey": secret}}, headers=H(runner)),
        # 異常の説明に秘密(未登録でなくても失敗する形: 長すぎる説明)
        client.post("/v1/runner/fault", json={"description": secret * 30}, headers=H(runner)),
        # 取り消しの理由に秘密(存在しないジョブ)
        client.post("/v1/jobs/no-such-job/cancel", json={"reason": secret}, headers=H(alice)),
        # 認証情報に秘密(未知の値)
        client.get("/v1/queue", headers=H(f"ss_{secret}")),
        client.get("/v1/queue", headers={"Authorization": f"Bearer {secret}"}),
        # 壊れた本文
        client.post(
            "/v1/jobs", content=f"{{{secret}".encode(), headers={**H(alice), "content-type": "application/json"}
        ),
        # 認証基盤の証明に秘密
        client.post("/v1/auth/login", json={"proof": {"subject": ""}, "delivery": secret}),
    ]


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(secret=SECRETS)
def test_secrets_in_inputs_never_appear_in_error_responses_or_logs(
    secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    api = build_api()
    api.register_runner("r-a")
    created = api.client.post("/v1/runners", json={"name": "r-b"}, headers=H(api.admin())).json()
    tokens = {
        "alice": api.member("alice"),
        "viewer": api.viewer(),
        "admin": api.admin(),
        "runner": created["token"]["token"],
    }
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        responses = failing_calls(api, secret, tokens)
    for response in responses:
        assert response.status_code >= 400  # type: ignore[attr-defined]
        assert secret not in response.text  # type: ignore[attr-defined]
        assert secret not in str(dict(response.headers))  # type: ignore[attr-defined]
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in log_text


def test_unknown_exception_is_internal_error_without_details() -> None:
    api = build_api()
    router = APIRouter()

    @router.get("/v1/_boom")
    def boom() -> None:
        raise RuntimeError("password=hunter2 at /srv/internal/path.py")

    api.app.include_router(router)
    client = TestClient(api.app, client=("127.0.0.1", 1), raise_server_exceptions=False)
    response = client.get("/v1/_boom")
    assert response.status_code == 500 and response.json()["code"] == "internal_error"
    assert "hunter2" not in response.text and "path.py" not in response.text
    assert set(response.json()) == {"type", "title", "status", "code", "detail", "request_id"}


def test_the_internal_error_content_goes_only_to_the_server_log_with_the_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = build_api()
    router = APIRouter()

    @router.get("/v1/_boom")
    def boom() -> None:
        raise RuntimeError("diagnostic-detail")

    api.app.include_router(router)
    client = TestClient(api.app, client=("127.0.0.1", 1), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="job_core_api.errors"):
        response = client.get("/v1/_boom")
    request_id = response.json()["request_id"]
    assert any(request_id in record.getMessage() for record in caplog.records)
