"""バックオフ・再試行・確定の拒否の判定・CoreClient の秘密の扱い(T087。研究 R13)。"""

from __future__ import annotations

import asyncio
import random

import httpx
import pytest

from job_runner_agent.core_client import CoreClient, CoreRejected, CoreUnavailable
from job_runner_agent.retry import backoff_delays, retry_unavailable
from job_runner_agent.secret_source import SecretValue

TOKEN = "rt_unit-test-token-0123456789"


def test_backoff_grows_to_the_cap_with_bounded_jitter() -> None:
    delays = backoff_delays(rng=random.Random(1))
    values = [next(delays) for _ in range(12)]
    expected = [1, 2, 4, 8, 16, 32, 60, 60, 60, 60, 60, 60]
    for value, base in zip(values, expected, strict=True):
        assert base * 0.8 <= value <= base * 1.2


def test_retry_unavailable_retries_until_success_and_stops_on_request() -> None:
    attempts: list[int] = []
    slept: list[float] = []

    async def operation() -> str:
        attempts.append(1)
        if len(attempts) < 4:
            raise CoreUnavailable("down")
        return "ok"

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    assert asyncio.run(retry_unavailable(operation, sleep=sleep)) == "ok"
    assert (len(attempts) == 4 and len(slept) == 3 and slept == sorted(slept)) or len(slept) == 3

    async def never() -> str:
        raise CoreUnavailable("down")

    stop_after = iter([False, False, True])
    result = asyncio.run(retry_unavailable(never, sleep=sleep, should_stop=lambda: next(stop_after)))
    assert result is None


def test_rejections_are_not_retried() -> None:
    calls: list[int] = []

    async def operation() -> None:
        calls.append(1)
        raise CoreRejected(409, "lease_expired")

    with pytest.raises(CoreRejected) as info:
        asyncio.run(retry_unavailable(operation))
    assert calls == [1] and info.value.final


@pytest.mark.parametrize(
    ("status", "code", "final"),
    [
        (409, "invalid_state_transition", True),
        (409, "lease_expired", True),
        (409, "target_not_running", True),
        (403, "runner_mismatch", True),
        (404, "job_not_found", True),
        (409, "log_quota_exceeded", False),
        (401, "authentication_failed", False),
        (422, "validation_failed", False),
    ],
)
def test_final_rejection_classification(status: int, code: str, final: bool) -> None:
    assert CoreRejected(status, code).final is final


def make_client(handler: httpx.MockTransport) -> CoreClient:
    return CoreClient("http://core.invalid", SecretValue(TOKEN), transport=handler, allow_insecure=True)


def test_client_maps_failures_and_never_exposes_the_token_or_bodies() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(503, text=f"upstream error echoing {TOKEN}")
        if request.url.path.endswith("/registration"):
            return httpx.Response(422, json={"code": "invalid_declaration", "detail": f"leak {TOKEN}"})
        raise httpx.ConnectError(f"cannot connect with {TOKEN}", request=request)

    client = make_client(httpx.MockTransport(respond))

    async def go() -> None:
        with pytest.raises(CoreUnavailable) as unavailable:
            await client.heartbeat()
        assert TOKEN not in str(unavailable.value) and TOKEN not in repr(unavailable.value)
        with pytest.raises(CoreRejected) as rejected:
            await client.register({"k": "v"})
        assert rejected.value.code == "invalid_declaration" and TOKEN not in str(rejected.value)
        with pytest.raises(CoreUnavailable) as network:
            await client.request_job()
        assert TOKEN not in str(network.value) and "cannot connect" not in str(network.value)

    asyncio.run(go())
    assert TOKEN not in repr(client)


def test_client_refuses_plain_http_unless_dev_and_sends_bearer_only_to_the_configured_host() -> None:
    with pytest.raises(ValueError):
        CoreClient("http://core.example", SecretValue(TOKEN))
    seen: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers["authorization"]))
        return httpx.Response(
            200,
            json={
                "state": "online",
                "lease_expires_at": None,
                "heartbeat_interval_seconds": 5,
                "abort_requested": False,
            },
        )

    asyncio.run(make_client(httpx.MockTransport(respond)).heartbeat())
    assert seen == [("core.invalid", f"Bearer {TOKEN}")]


def test_redirects_are_not_followed_and_malformed_responses_are_unavailable() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://elsewhere.invalid/"})

    async def go() -> None:
        with pytest.raises(CoreUnavailable) as info:  # 3xx・形式の不正は、成功でも拒否でもなく再試行の対象
            await make_client(httpx.MockTransport(respond)).heartbeat()
        assert TOKEN not in str(info.value)

    asyncio.run(go())
