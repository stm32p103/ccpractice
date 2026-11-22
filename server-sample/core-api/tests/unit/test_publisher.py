"""通知の組み立て(research.md R9)。写像の表が状態を変える操作を網羅すること、失敗・拒否は発行しないこと。"""

from __future__ import annotations

from job_core_api.events.ports import ChangeType
from job_core_api.events.publisher import NO_PUBLISH, PUBLISHES
from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers
STATE_CHANGING = {"post", "put", "delete", "patch"}


def drain(api: ApiFixture):  # type: ignore[no-untyped-def]
    subscription = api.deps.broker.subscribe(f"{api.deps.broker.epoch}:0", frozenset({"job", "runner", "queue"}))
    events = []
    while (event := subscription.next(0.0)) is not None:
        events.append(event)
    return events


def test_the_mapping_tables_cover_every_state_changing_operation() -> None:
    spec = build_api().app.openapi()
    operations = {
        op["operationId"] for item in spec["paths"].values() for method, op in item.items() if method in STATE_CHANGING
    }
    covered = set(PUBLISHES) | set(NO_PUBLISH)
    assert operations - covered == set(), "通知の写像の表にない操作がある"
    assert covered - operations == set(), "表にあるが API にない操作がある"
    assert not set(PUBLISHES) & set(NO_PUBLISH)


def test_rejected_and_failed_operations_publish_nothing() -> None:
    api = build_api()
    api.register_runner()
    before = len(drain(api))
    viewer = api.viewer()
    assert api.client.post("/v1/jobs", json=submit_body(), headers=H(viewer)).status_code == 403
    assert api.client.post("/v1/jobs/none/cancel", json={}, headers=H(api.member())).status_code == 404
    assert api.client.post("/v1/jobs", json={"bad": 1}, headers=H(api.member())).status_code == 400
    assert len(drain(api)) == before


def test_a_failing_broker_does_not_change_the_use_case_result() -> None:
    api = build_api()
    api.register_runner()

    class Broken:
        epoch = "x"
        last_seq = 0

        def publish(self, change: object) -> None:
            raise RuntimeError("broker down")

    api.deps.publisher._broker = Broken()  # type: ignore[assignment]
    response = api.client.post("/v1/jobs", json=submit_body(), headers=H(api.member()))
    assert response.status_code == 201
    assert api.client.get(f"/v1/jobs/{response.json()['job_id']}", headers=H(api.member())).status_code == 200


def test_runner_state_changes_are_derived_from_snapshots_without_duplicates() -> None:
    api = build_api()
    admin = api.admin()
    api.client.post("/v1/runners", json={"name": "r-a"}, headers=H(admin))
    events = [e for e in drain(api) if e.type is ChangeType.RUNNER_CHANGED]
    assert [e.change.value for e in events] == ["created"]  # type: ignore[union-attr]
    api.deps.publisher.runner_event()
    assert len([e for e in drain(api) if e.type is ChangeType.RUNNER_CHANGED]) == 1
