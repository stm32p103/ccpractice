"""US5-1〜3: 一覧の絞り込み・頁送り、待機列の全体の参照(spec US5)。"""

from __future__ import annotations

from datetime import timedelta

from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def make_jobs(api: ApiFixture, token: str, n: int, start: int = 0) -> list[str]:
    ids = []
    for i in range(start, start + n):
        response = api.client.post("/v1/jobs", json=submit_body(definition_payload={"n": i}), headers=H(token))
        assert response.status_code == 201
        ids.append(response.json()["job_id"])
        api.advance(timedelta(seconds=1))
    return ids


def test_us5_1_filters_by_state_submitter_and_period() -> None:
    api = build_api()
    api.register_runner()
    alice, bob = api.member("alice"), api.member("bob")
    a_ids = make_jobs(api, alice, 2)
    mid = api.core.clock.peek()
    b_ids = make_jobs(api, bob, 2, start=10)
    api.client.post(f"/v1/jobs/{a_ids[0]}/cancel", json={}, headers=H(alice))
    viewer = api.viewer()

    everything = api.client.get("/v1/jobs", headers=H(viewer)).json()
    assert [j["job_id"] for j in everything["items"]] == list(reversed(a_ids + b_ids))
    cancelled = api.client.get("/v1/jobs", params={"state": "cancelled"}, headers=H(viewer)).json()["items"]
    assert [j["job_id"] for j in cancelled] == [a_ids[0]]
    two_states = api.client.get("/v1/jobs", params=[("state", "cancelled"), ("state", "queued")], headers=H(viewer))
    assert len(two_states.json()["items"]) == 4
    bobs = api.client.get("/v1/jobs", params={"submitter": "bob"}, headers=H(viewer)).json()["items"]
    assert {j["owner"] for j in bobs} == {"bob"} and len(bobs) == 2
    period = api.client.get("/v1/jobs", params={"submitted_from": mid.isoformat()}, headers=H(viewer)).json()["items"]
    assert [j["job_id"] for j in period] == list(reversed(b_ids))
    before = api.client.get("/v1/jobs", params={"submitted_to": mid.isoformat()}, headers=H(viewer)).json()["items"]
    assert [j["job_id"] for j in before] == list(reversed(a_ids))
    assert "payload" not in everything["items"][0] and "definition" not in everything["items"][0]


def test_us5_2_paging_has_no_overlap_or_gap_across_changes() -> None:
    api = build_api()
    api.register_runner()
    alice = api.member("alice")
    ids = make_jobs(api, alice, 7)
    viewer = api.viewer()
    first = api.client.get("/v1/jobs", params={"limit": 3}, headers=H(viewer)).json()
    assert len(first["items"]) == 3 and first["next_cursor"]
    # 頁の間で、状態の変化と新しい提出が起きても、継ぎ目は変わらない
    api.client.post(f"/v1/jobs/{ids[2]}/cancel", json={}, headers=H(alice))
    make_jobs(api, alice, 1, start=100)
    second = api.client.get("/v1/jobs", params={"limit": 3, "cursor": first["next_cursor"]}, headers=H(viewer)).json()
    third = api.client.get("/v1/jobs", params={"limit": 3, "cursor": second["next_cursor"]}, headers=H(viewer)).json()
    seen = [j["job_id"] for page in (first, second, third) for j in page["items"]]
    assert seen == list(reversed(ids)) and third["next_cursor"] is None


def test_us5_2_limits_and_invalid_cursor() -> None:
    api = build_api()
    viewer = api.viewer()
    assert api.client.get("/v1/jobs", params={"limit": 0}, headers=H(viewer)).status_code == 400
    assert api.client.get("/v1/jobs", params={"limit": 201}, headers=H(viewer)).status_code == 400
    bad = api.client.get("/v1/jobs", params={"cursor": "garbage"}, headers=H(viewer))
    assert bad.status_code == 422 and bad.json()["field"] == "cursor"
    assert api.client.get("/v1/jobs", params={"state": "nope"}, headers=H(viewer)).status_code == 400
    assert api.client.get("/v1/jobs").status_code == 401


def test_us5_3_queue_is_ordered_visible_to_everyone_and_grants_nothing_else() -> None:
    api = build_api()
    api.register_runner()
    alice, op = api.member("alice"), api.operator("op")
    j1, j2, j3 = make_jobs(api, alice, 3)
    api.client.post(
        f"/v1/jobs/{j3}/reschedule", json={"placement": {"anchor_job_id": j1, "side": "before"}}, headers=H(op)
    )
    viewer = api.viewer()
    queue = api.client.get("/v1/queue", headers=H(viewer)).json()["items"]
    assert [j["job_id"] for j in queue] == [j3, j1, j2] and [j["position"] for j in queue] == [1, 2, 3]
    assert all(j["state"] == "queued" for j in queue) and "payload" not in queue[0]
    # 閲覧は、他の操作の権限を意味しない
    assert api.client.post(f"/v1/jobs/{j1}/cancel", json={}, headers=H(viewer)).status_code == 403
    assert api.client.post("/v1/jobs", json=submit_body(), headers=H(viewer)).status_code == 403
    # 認証のない呼び出しと、general を持たない主体は閲覧できない
    assert api.client.get("/v1/queue").status_code == 401
    nobody = api.issue_service_token([])
    assert api.client.get("/v1/queue", headers=H(nobody)).status_code == 403


def test_running_jobs_leave_the_queue_but_stay_in_the_history() -> None:
    api = build_api()
    runner_id, runner = api.register_runner()
    alice = api.member("alice")
    j1, j2 = make_jobs(api, alice, 2)
    assert api.assign_next(runner_id, runner) == j1
    viewer = api.viewer()
    assert [j["job_id"] for j in api.client.get("/v1/queue", headers=H(viewer)).json()["items"]] == [j2]
    running = api.client.get("/v1/jobs", params={"state": "running"}, headers=H(viewer)).json()["items"]
    assert [j["job_id"] for j in running] == [j1] and running[0]["position"] is None
