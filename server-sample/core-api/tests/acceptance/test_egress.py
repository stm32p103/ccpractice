"""外向きの通信の検査(SC-009、FR-023・FR-024。憲章 S1・S2。quickstart V27)。

ログイン・提出・購読・ランナーの一巡のあいだ、外向きの通信が 0 件であること。ループバック以外への接続の試みを
検知する(ソケットの接続をすべて記録し、許す宛先はこのテストが起動する、自分自身のサーバーだけ)。
API が静的資産・外部のフォント・テレメトリを返さず・読まないことも確かめる。
"""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Iterator
from typing import Any

import pytest

from job_testing.api_fakes import ApiFixture, SseReader, build_api, live_server, submit_body

H = ApiFixture.headers
LOOPBACK = ("127.0.0.1", "::1", "localhost")


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """ソケットの接続の宛先をすべて記録する(接続そのものは通す。ループバックだけを許す)。"""
    attempts: list[Any] = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def record(address: Any) -> None:
        attempts.append(address)
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            raise ConnectionRefusedError("外向きの接続は許可されない(試験)")

    def connect(self: socket.socket, address: Any) -> None:
        record(address)
        original_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        record(address)
        return original_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    yield attempts


def test_a_full_round_trip_makes_no_outbound_connection(connections: list[Any]) -> None:
    api = build_api()
    with live_server(api.app) as url:
        import httpx

        def call(method: str, path: str, token: str | None = None, **kwargs: Any) -> httpx.Response:
            headers = H(token) if token else {}
            return httpx.request(method, url + path, headers=headers, timeout=10, **kwargs)

        session = call(
            "POST", "/v1/auth/login", json={"proof": {"subject": "root", "groups": "g-admin"}, "delivery": "token"}
        )
        admin = session.json()["session_token"]
        reader = SseReader(url, H(admin))
        reader.next_event()
        call("PUT", "/v1/capability-allowlist", admin, json={"entries": {"k1": "single"}})
        runner = call("POST", "/v1/runners", admin, json={"name": "r-a"}).json()["token"]["token"]
        call("POST", "/v1/runner/registration", runner, json={"capabilities": {"k1": "v"}})
        job = call("POST", "/v1/jobs", admin, json=submit_body()).json()["job_id"]
        call("POST", "/v1/runner/job-requests", runner)
        call("POST", f"/v1/runner/jobs/{job}/result", runner, json={"outcome": "succeeded"})
        call("GET", "/v1/jobs", admin)
        reader.collect(3)
        reader.close()
    assert connections, "試験の自分自身のサーバーへの接続が記録されていない(検知が働いていない)"
    outbound = [a for a in connections if (a[0] if isinstance(a, tuple) else a) not in LOOPBACK]
    assert outbound == []


def test_responses_reference_no_external_resources_and_no_static_assets_are_served() -> None:
    api = build_api()
    token = api.admin()
    spec_text = json.dumps(api.app.openapi())
    assert re.findall(r"https?://(?!127\.0\.0\.1|localhost)[\w.-]+", spec_text) == []
    for path in ("/", "/static/app.js", "/favicon.ico", "/docs", "/redoc", "/assets/font.woff2"):
        assert api.client.get(path, headers=H(token)).status_code in {404, 405}
    for response in (api.client.get("/healthz"), api.client.get("/v1/queue", headers=H(token))):
        assert "link" not in response.headers
        body = response.text
        assert "<script" not in body and "<link" not in body and not re.search(r"https?://", body)


def test_no_telemetry_or_analytics_exporters_are_loaded_by_the_api() -> None:
    import sys

    banned = {"sentry_sdk", "newrelic", "datadog", "ddtrace", "segment", "mixpanel"}
    banned_prefixes = ("opentelemetry.sdk", "opentelemetry.exporter")
    build_api()
    assert not banned & set(sys.modules)
    assert [m for m in sys.modules if m.startswith(banned_prefixes)] == []


def test_the_frameworks_native_telemetry_is_disabled_even_when_the_environment_asks_for_export(
    monkeypatch: pytest.MonkeyPatch, connections: list[Any]
) -> None:
    """環境変数でテレメトリの書き出しが指定されても、API は使わない(FastAPI の組み込みのテレメトリ。S2)。"""
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://telemetry.invalid:4318")
    api = build_api()
    assert api.app._telemetry["auto_configure"] is False  # type: ignore[attr-defined]
    assert all(api.app._telemetry[k] is False for k in ("tracing", "metrics", "logs", "operation_spans"))  # type: ignore[attr-defined,literal-required]
    assert api.app._native_telemetry.enabled() is False  # type: ignore[attr-defined]
    api.client.post("/v1/jobs", json={"bad": 1}, headers=H(api.member()))
    assert [c for c in connections if "invalid" in str(c)] == []
