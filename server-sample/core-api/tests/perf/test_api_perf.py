"""性能の目安(SC-010。quickstart V28)。既定では実行しない(`-m perf` で実行)。

50 人の同時の利用者(ループバックの実サーバー)で、提出・一覧・詳細・待機列が 2 秒以内。認証の照合と権限の導出は
1 呼び出しあたり数ミリ秒の範囲。SSE の接続 200 での通知の遅延。
"""

from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from job_core_api.settings import ApiSettings
from job_testing.api_fakes import ApiFixture, SseReader, build_api, live_server, submit_body

pytestmark = pytest.mark.perf
H = ApiFixture.headers
USERS = 50
LIMIT_SECONDS = 2.0


def test_fifty_concurrent_users_get_responses_within_two_seconds() -> None:
    api = build_api(settings=ApiSettings(sse_heartbeat_seconds=15))
    api.register_runner()
    tokens = [api.member(f"user{i}") for i in range(USERS)]
    with live_server(api.app) as url:
        timings: dict[str, list[float]] = {"submit": [], "list": [], "detail": [], "queue": []}

        def worker(index: int) -> None:
            with httpx.Client(base_url=url, headers=H(tokens[index]), timeout=10) as client:
                for round_ in range(5):
                    body = submit_body(definition_payload={"user": index, "round": round_})
                    started = time.perf_counter()
                    response = client.post("/v1/jobs", json=body)
                    timings["submit"].append(time.perf_counter() - started)
                    assert response.status_code == 201
                    job_id = response.json()["job_id"]
                    for name, path in (("list", "/v1/jobs"), ("detail", f"/v1/jobs/{job_id}"), ("queue", "/v1/queue")):
                        started = time.perf_counter()
                        assert client.get(path).status_code == 200
                        timings[name].append(time.perf_counter() - started)

        with ThreadPoolExecutor(max_workers=USERS) as pool:
            list(pool.map(worker, range(USERS)))
    for name, values in timings.items():
        assert len(values) == USERS * 5
        assert max(values) < LIMIT_SECONDS, (name, max(values))
        print(f"{name}: median={statistics.median(values) * 1000:.1f}ms max={max(values) * 1000:.1f}ms")


def test_authentication_and_permission_derivation_take_milliseconds() -> None:
    api = build_api()
    token = api.login_as("u1", ["g-admin"])
    started = time.perf_counter()
    for _ in range(1000):
        api.deps.authenticator.authenticate(token, source="127.0.0.1")
    per_call = (time.perf_counter() - started) / 1000
    assert per_call < 0.005, f"{per_call * 1000:.2f}ms"


def test_two_hundred_sse_connections_receive_changes_quickly() -> None:
    api = build_api(settings=ApiSettings(sse_max_connections=200, sse_heartbeat_seconds=15))
    api.register_runner()
    with live_server(api.app) as url:
        readers = [SseReader(url, H(api.viewer(f"v{i}"))) for i in range(200)]
        try:
            assert all(r.status == 200 for r in readers)
            for reader in readers:
                reader.next_event()  # hello
            started = time.perf_counter()
            httpx.post(url + "/v1/jobs", json=submit_body(), headers=H(api.member()), timeout=10)
            latencies = []
            for reader in readers:
                assert reader.next_event(timeout=3) is not None
                latencies.append(time.perf_counter() - started)
            assert max(latencies) < 3.0, max(latencies)
        finally:
            for reader in readers:
                reader.close()
