"""境界のミドルウェア(research.md R10、R11、T-A1、T-A6)。"""

from __future__ import annotations

import logging

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from job_core_api.http.middleware import BoundaryMiddleware
from job_core_api.settings import ApiSettings


async def echo(request: Request) -> JSONResponse:
    body = await request.body()
    request.state.principal_kind = "human"
    request.state.principal_id = "u1"
    return JSONResponse({"size": len(body), "request_id": request.state.request_id})


def make_client(settings: ApiSettings, address: str = "127.0.0.1") -> TestClient:
    app = Starlette(routes=[Route("/v1/echo", echo, methods=["GET", "POST"]), Route("/other", echo)])
    app.add_middleware(BoundaryMiddleware, settings=settings)
    return TestClient(app, client=(address, 50000))


def test_allowed_source_passes_and_headers_are_added() -> None:
    response = make_client(ApiSettings()).get("/v1/echo")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_source_outside_allow_list_is_rejected_before_anything_else() -> None:
    response = make_client(ApiSettings(allowed_networks=("10.0.0.0/8",))).get("/v1/echo")
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "network_not_allowed" and body["request_id"] == response.headers["x-request-id"]
    assert set(body) == {"type", "title", "status", "code", "detail", "request_id"}


def test_forwarded_header_is_not_trusted() -> None:
    client = make_client(ApiSettings(allowed_networks=("10.0.0.0/8",)), address="8.8.8.8")
    assert client.get("/v1/echo", headers={"X-Forwarded-For": "10.1.1.1"}).status_code == 403


def test_request_id_is_taken_from_a_valid_header_only() -> None:
    client = make_client(ApiSettings())
    assert client.get("/v1/echo", headers={"X-Request-Id": "abc-123_X"}).headers["x-request-id"] == "abc-123_X"
    for bad in ["a b", "x" * 65, "日本語"]:
        got = client.get("/v1/echo", headers={"X-Request-Id": bad.encode("utf-8")}).headers["x-request-id"]
        assert got != bad and len(got) == 32


def test_body_over_limit_is_413_by_content_length() -> None:
    client = make_client(ApiSettings(max_body_bytes=10))
    assert client.post("/v1/echo", content=b"x" * 10).status_code == 200
    response = client.post("/v1/echo", content=b"x" * 11)
    assert response.status_code == 413 and response.json()["code"] == "payload_too_large"


def test_body_over_limit_without_content_length_is_413() -> None:
    client = make_client(ApiSettings(max_body_bytes=10))

    def chunks():  # type: ignore[no-untyped-def]
        yield b"x" * 8
        yield b"x" * 8

    response = client.post("/v1/echo", content=chunks())
    assert response.status_code == 413


def test_access_log_has_no_credentials_query_or_body(caplog: pytest.LogCaptureFixture) -> None:
    client = make_client(ApiSettings())
    with caplog.at_level(logging.INFO, logger="job_core_api.access"):
        client.post(
            "/v1/echo?token=QUERYSECRET",
            content=b"BODYSECRET",
            headers={"Authorization": "Bearer ss_HEADERSECRET", "Cookie": "__Host-session=COOKIESECRET"},
        )
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("QUERYSECRET", "BODYSECRET", "HEADERSECRET", "COOKIESECRET", "Bearer"):
        assert secret not in text
    assert "method=POST" in text and "path=/v1/echo" in text and "status=200" in text
    assert "principal_kind=human" in text and "principal=u1" in text


def test_non_v1_paths_do_not_get_no_store() -> None:
    assert "cache-control" not in make_client(ApiSettings()).get("/other").headers
