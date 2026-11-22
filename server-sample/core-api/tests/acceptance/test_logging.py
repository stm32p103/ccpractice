"""アクセスログと request_id の検査(research.md R10。S4、T-A1)。"""

from __future__ import annotations

import logging

import pytest

from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def test_access_log_has_no_credentials_cookies_query_or_body(caplog: pytest.LogCaptureFixture) -> None:
    api = build_api()
    api.register_runner()
    token = api.member("alice")
    with caplog.at_level(logging.DEBUG):
        api.client.post(
            "/v1/jobs?secretquery=QUERYSECRET",
            json=submit_body(definition_payload={"x": "BODYSECRET"}),
            headers={**H(token), "Cookie": "other=COOKIESECRET"},
        )
        api.client.get("/v1/queue", headers=H("ss_HEADERSECRETVALUE"))
        api.client.post("/v1/auth/login", json={"proof": {"subject": "u1", "password": "PASSWORDSECRET"}})
    # サーバー(job_core_api)のログだけを検査する(テストのクライアントのライブラリのログは対象外)
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("job_core_api"))
    for secret in ("QUERYSECRET", "BODYSECRET", "COOKIESECRET", "HEADERSECRET", "PASSWORDSECRET", token):
        assert secret not in text
    assert "principal_kind=human" in text and "principal=alice" in text


def test_request_id_matches_between_response_problem_and_log(caplog: pytest.LogCaptureFixture) -> None:
    api = build_api()
    with caplog.at_level(logging.INFO, logger="job_core_api.access"):
        response = api.client.get("/v1/queue", headers={"X-Request-Id": "trace-me-123"})
    assert response.headers["x-request-id"] == "trace-me-123" == response.json()["request_id"]
    assert any("request_id=trace-me-123" in r.getMessage() for r in caplog.records)


def test_generated_request_id_is_used_when_the_supplied_one_is_malformed() -> None:
    api = build_api()
    for bad in ("has space", "x" * 65, "semi;colon", "<script>"):
        response = api.client.get("/v1/queue", headers={"X-Request-Id": bad})
        assert response.headers["x-request-id"] != bad
        assert response.json()["request_id"] == response.headers["x-request-id"]


def test_log_lines_cannot_be_forged_through_the_path(caplog: pytest.LogCaptureFixture) -> None:
    api = build_api()
    with caplog.at_level(logging.INFO, logger="job_core_api.access"):
        api.client.get("/v1/jobs/abc%0Amethod=GET status=200 forged", headers=H(api.viewer()))
    messages = [r.getMessage() for r in caplog.records]
    assert all("\n" not in m for m in messages)
