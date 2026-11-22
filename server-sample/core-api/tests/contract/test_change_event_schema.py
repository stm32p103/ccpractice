"""通知のスキーマ検査(contracts/change-event.schema.json。FR-018、T-A8)。

発行されるすべての通知が、スキーマに適合する。変更の発生元(提出、位置指定、スケジュール変更、割り当て、完了、
取り消し、中断の要求、やり直し、ランナーの作成・登録・offline・maintenance・異常・削除)ごとに 1 件以上を確かめる。
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import jsonschema

from job_core_api.events.ports import ChangeEvent
from job_core_api.events.sse import event_json
from job_core_api.scheduler import Scheduler
from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "specs/003-core-api/contracts/change-event.schema.json").read_text("utf-8")
)


def all_events(api: ApiFixture) -> list[ChangeEvent]:
    subscription = api.deps.broker.subscribe(f"{api.deps.broker.epoch}:0", frozenset({"job", "runner", "queue"}))
    events = []
    while (event := subscription.next(0.0)) is not None:
        events.append(event)
    subscription.close()
    return events


def test_every_published_event_conforms_and_every_source_is_covered() -> None:
    api = build_api()
    admin, alice, op = api.admin(), api.member("alice"), api.operator("op")
    created = api.client.post("/v1/runners", json={"name": "r-a"}, headers=H(admin)).json()
    runner_id, token = created["runner_id"], created["token"]["token"]
    api.client.put("/v1/capability-allowlist", json={"entries": {"k1": "single"}}, headers=H(admin))
    api.client.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=H(token))

    j1 = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    j2 = api.client.post("/v1/jobs", json=submit_body(definition_payload={"n": 2}), headers=H(alice)).json()["job_id"]
    api.client.post(
        f"/v1/jobs/{j2}/reschedule", json={"placement": {"anchor_job_id": j1, "side": "before"}}, headers=H(op)
    )
    api.client.post(f"/v1/jobs/{j2}/cancel", json={}, headers=H(alice))  # 待機中の取り消し
    api.client.post("/v1/jobs", json=submit_body(definition_payload={"n": 3}), headers=H(alice))
    api.client.post("/v1/runner/job-requests", headers=H(token))  # j1 を割り当て
    api.client.post(f"/v1/jobs/{j1}/cancel", json={"reason": "stop"}, headers=H(op))  # 中断の要求
    api.client.post(f"/v1/runner/jobs/{j1}/stopped", headers=H(token))
    retried = api.client.post(f"/v1/jobs/{j2}/retry", json={}, headers=H(alice)).json()["job_id"]
    assigned = api.client.post("/v1/runner/job-requests", headers=H(token)).json()["assignment"]["job_id"]
    assert retried
    api.client.post(f"/v1/runner/jobs/{assigned}/result", json={"outcome": "succeeded"}, headers=H(token))
    api.client.post("/v1/runner/fault", json={"description": "x"}, headers=H(token))
    api.client.delete("/v1/runner/fault", headers=H(token))
    api.client.put(f"/v1/runners/{runner_id}/maintenance", json={}, headers=H(admin))
    api.client.delete(f"/v1/runners/{runner_id}/maintenance", headers=H(admin))
    api.advance(timedelta(hours=1))
    Scheduler(api.deps).run_sweep()  # offline 化
    api.client.delete(f"/v1/runners/{runner_id}", headers=H(admin))

    events = all_events(api)
    for event in events:
        jsonschema.validate(json.loads(event_json(event)), SCHEMA, format_checker=jsonschema.FormatChecker())
    seqs = [e.seq for e in events]
    assert seqs == list(range(1, len(events) + 1))
    changes = {e.change.value for e in events if e.change}
    expected = {
        "submitted",
        "rescheduled",
        "assigned",
        "completed",
        "cancel_requested",
        "cancelled",
        "retried",
        "created",
        "registered",
        "offline",
        "maintenance_changed",
        "fault_changed",
        "deleted",
    }
    assert expected <= changes, expected - changes
    assert {e.type.value for e in events} == {"job.changed", "runner.changed", "queue.changed"}


def test_event_json_keys_are_fixed() -> None:
    api = build_api()
    api.client.post("/v1/runners", json={"name": "r"}, headers=H(api.admin()))
    [event] = [e for e in all_events(api) if e.type.value == "runner.changed"]
    assert set(json.loads(event_json(event))) == {"seq", "epoch", "type", "occurred_at", "subject", "state", "change"}
