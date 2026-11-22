"""US6-1〜3: 状態の変更を SSE で受け取る(spec US6。SC-007)。ループバックの実サーバーで試験する。"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest

from job_core_api.settings import ApiSettings
from job_testing.api_fakes import ApiFixture, SseReader, build_api, live_server, submit_body
from job_testing.api_fakes.build_api import ADMIN_PRINCIPAL

H = ApiFixture.headers
SCHEMA_KEYS = {"seq", "epoch", "type", "occurred_at", "subject", "state", "change"}


@pytest.fixture
def live() -> Iterator[tuple[ApiFixture, str]]:
    api = build_api(settings=ApiSettings(sse_heartbeat_seconds=1))
    api.register_runner("r-a")
    with live_server(api.app) as url:
        yield api, url


def post(url: str, path: str, token: str, **kwargs: object) -> httpx.Response:
    return httpx.post(url + path, headers=H(token), timeout=10, **kwargs)  # type: ignore[arg-type]


def test_us6_1_changes_arrive_within_three_seconds_with_a_hello_first(live: tuple[ApiFixture, str]) -> None:
    api, url = live
    alice = api.member("alice")
    reader = SseReader(url, H(api.viewer()))
    try:
        assert reader.status == 200 and reader.response_headers["content-type"].startswith("text/event-stream")
        hello = reader.next_event()
        assert hello is not None and hello.event == "hello" and hello.json()["heartbeat_seconds"] == 1
        started = time.monotonic()
        response = post(url, "/v1/jobs", alice, json=submit_body())
        job_id = response.json()["job_id"]
        events = reader.collect(2)
        assert time.monotonic() - started < 3
        assert [e.event for e in events] == ["job.changed", "queue.changed"]
        body = events[0].json()
        assert body["subject"] == {"kind": "job", "id": job_id} and body["change"] == "submitted"
        assert body["state"] == "queued" and events[0].id == f"{body['epoch']}:{body['seq']}"
    finally:
        reader.close()


def test_us6_1_runner_and_job_lifecycle_events(live: tuple[ApiFixture, str]) -> None:
    api, url = live
    admin, alice = api.admin(), api.member("alice")
    reader = SseReader(url, H(api.viewer()))
    try:
        reader.next_event()  # hello
        created = post(url, "/v1/runners", admin, json={"name": "r-new"}).json()
        event = reader.next_event()
        assert event is not None and event.event == "runner.changed"
        assert event.json()["subject"] == {"kind": "runner", "id": created["runner_id"]}
        assert event.json()["change"] == "created"
        job_id = post(url, "/v1/jobs", alice, json=submit_body()).json()["job_id"]
        reader.collect(2)
        runner = next(r for r in api.core.list_runners(ADMIN_PRINCIPAL) if r.name == "r-a")
        token = api.core.reissue_token(ADMIN_PRINCIPAL, runner_id=runner.runner_id).value
        assigned = post(url, "/v1/runner/job-requests", token).json()["assignment"]
        assert assigned["job_id"] == job_id
        kinds = [(e.event, e.json().get("change")) for e in reader.collect(4, timeout=5)]
        assert ("job.changed", "assigned") in kinds and ("queue.changed", None) in kinds
        post(url, f"/v1/runner/jobs/{job_id}/result", token, json={"outcome": "succeeded"})
        kinds = [(e.event, e.json().get("change")) for e in reader.collect(3, timeout=5)]
        assert ("job.changed", "completed") in kinds
    finally:
        reader.close()


def test_us6_2_last_event_id_replays_missed_events(live: tuple[ApiFixture, str]) -> None:
    api, url = live
    alice = api.member("alice")
    first = SseReader(url, H(api.viewer()))
    first.next_event()  # hello
    post(url, "/v1/jobs", alice, json=submit_body())
    seen = first.collect(2)
    last_id = seen[-1].id
    first.close()
    post(url, "/v1/jobs", alice, json=submit_body(definition_payload={"n": 2}))
    second = SseReader(url, {**H(api.viewer()), "Last-Event-ID": last_id or ""})
    try:
        second.next_event()  # hello
        replayed = second.collect(2)
        assert [e.event for e in replayed] == ["job.changed", "queue.changed"]
        assert all(int(e.id.split(":")[1]) > int(last_id.split(":")[1]) for e in replayed)  # type: ignore[union-attr]
    finally:
        second.close()


def test_us6_2_out_of_range_or_other_epoch_gets_resync(live: tuple[ApiFixture, str]) -> None:
    api, url = live
    for bad in ("not-an-id", "other-epoch:3", f"{api.deps.broker.epoch}:999"):
        reader = SseReader(url, {**H(api.viewer()), "Last-Event-ID": bad})
        try:
            reader.next_event()  # hello
            event = reader.next_event()
            assert event is not None and event.event == "resync", bad
        finally:
            reader.close()


def test_us6_3_revocation_is_detected_within_the_interval_and_the_stream_closes(live: tuple[ApiFixture, str]) -> None:
    api, url = live
    token = api.viewer("v1")
    reader = SseReader(url, H(token))
    try:
        reader.next_event()  # hello
        api.sessions.revoke_all_of("v1", api.core.clock.now())  # type: ignore[arg-type]
        started = time.monotonic()
        expired = reader.next_event(timeout=6)
        assert expired is not None and expired.event == "auth.expired"
        assert time.monotonic() - started < 4
        assert reader.finished.wait(5)
    finally:
        reader.close()


def test_us6_3_losing_the_general_permission_ends_the_stream(live: tuple[ApiFixture, str]) -> None:
    import copy

    from job_core_api.access.config import AccessConfig
    from job_testing.api_fakes import DEFAULT_ACCESS

    api, url = live
    reader = SseReader(url, H(api.viewer("v1")))
    try:
        reader.next_event()
        config = copy.deepcopy(DEFAULT_ACCESS)
        config["roles"]["viewer"]["permissions"] = []
        api.deps.access.replace(AccessConfig.from_mapping(config))
        expired = reader.next_event(timeout=6)
        assert expired is not None and expired.event == "auth.expired"
    finally:
        reader.close()


def test_us6_3_access_is_refused_without_credentials_or_general(live: tuple[ApiFixture, str]) -> None:
    api, url = live
    anonymous = SseReader(url, {})
    assert anonymous.status == 401 and anonymous.finished.wait(5)
    no_general = SseReader(url, H(api.issue_service_token(["job.submit"])))
    assert no_general.status == 403 and "permission_denied" in no_general.body_on_error


def test_connection_limit_is_503_and_released_on_close() -> None:
    api = build_api(settings=ApiSettings(sse_max_connections=1, sse_heartbeat_seconds=1))
    with live_server(api.app) as url:
        first = SseReader(url, H(api.viewer()))
        first.next_event()
        second = SseReader(url, H(api.viewer()))
        assert second.status == 503 and "sse_capacity_exceeded" in second.body_on_error
        first.close()
        deadline = time.monotonic() + 5
        while api.deps.sse_connections.count and time.monotonic() < deadline:
            time.sleep(0.05)
        third = SseReader(url, H(api.viewer()))
        try:
            assert third.status == 200
        finally:
            third.close()


def test_topics_filter(live: tuple[ApiFixture, str]) -> None:
    api, url = live
    reader = SseReader(url, H(api.viewer()), params={"topics": "queue"})
    try:
        reader.next_event()
        post(url, "/v1/jobs", api.member("alice"), json=submit_body())
        events = reader.collect(1)
        assert [e.event for e in events] == ["queue.changed"]
        assert reader.next_event(timeout=0.5) is None
    finally:
        reader.close()


def test_events_carry_no_free_text(live: tuple[ApiFixture, str]) -> None:
    api, url = live
    admin, alice, op = api.admin(), api.member("alice"), api.operator("op")
    reader = SseReader(url, H(api.viewer()))
    try:
        reader.next_event()
        runner = api.core.list_runners(ADMIN_PRINCIPAL)[0]
        post(url, "/v1/runners", admin, json={"name": "SECRET-RUNNER-NAME"})
        job_id = post(url, "/v1/jobs", alice, json=submit_body(definition_payload={"x": "SECRET-PAYLOAD"})).json()[
            "job_id"
        ]
        runner_token = api.core.reissue_token(ADMIN_PRINCIPAL, runner_id=runner.runner_id).value
        post(url, "/v1/runner/job-requests", runner_token)
        post(url, "/v1/runner/fault", runner_token, json={"description": "SECRET-FAULT-DESCRIPTION"})
        post(url, f"/v1/jobs/{job_id}/cancel", op, json={"reason": "SECRET-REASON"})
        seen = []
        while (message := reader.next_event(timeout=1.5)) is not None:
            seen.append(message)
        assert len(seen) >= 6
        for message in seen:
            assert set(message.json()) <= SCHEMA_KEYS
            assert "SECRET" not in (message.data or "")
    finally:
        reader.close()


def test_idle_timeout_is_not_extended_by_an_open_stream() -> None:
    api = build_api(settings=ApiSettings(sse_heartbeat_seconds=1))
    with live_server(api.app) as url:
        token = api.viewer("v1")
        reader = SseReader(url, H(token))
        try:
            reader.next_event()
            time.sleep(1.5)  # 再確認が走っても、last_used_at は進まない
            session = api.sessions.all()[0]
            before = session.last_used_at
            api.advance(timedelta(hours=2, minutes=1))
            expired = reader.next_event(timeout=6)
            assert expired is not None and expired.event == "auth.expired"
            assert api.sessions.all()[0].last_used_at >= before
        finally:
            reader.close()
