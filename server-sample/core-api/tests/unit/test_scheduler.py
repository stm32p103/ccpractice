"""定期処理(research.md R20)。手動で進める時計で、offline 化・削除・通知・冪等を確かめる。"""

from __future__ import annotations

from datetime import timedelta

from job_core.access.permission import Permission
from job_core.access.principal import PrincipalKind
from job_core_api.events.ports import ChangeKind, ChangeType
from job_core_api.scheduler import SYSTEM_PRINCIPAL, Scheduler
from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers


def runner_events(api: ApiFixture):  # type: ignore[no-untyped-def]
    subscription = api.deps.broker.subscribe(f"{api.deps.broker.epoch}:0", frozenset({"runner"}))
    out = []
    while (event := subscription.next(0.0)) is not None:
        out.append(event)
    return out


def test_system_principal_has_only_the_two_fixed_permissions() -> None:
    assert SYSTEM_PRINCIPAL.kind is PrincipalKind.SYSTEM
    assert SYSTEM_PRINCIPAL.permissions == {Permission.RUNNER_SWEEP, Permission.RETENTION_PURGE}


def test_sweep_marks_silent_runners_offline_and_publishes_the_change() -> None:
    api = build_api()
    runner_id, _ = api.register_runner("r-a")
    scheduler = Scheduler(api.deps)
    assert scheduler.tick() == ["sweep", "purge", "sessions"]
    api.deps.publisher.runner_event(runner_id, ChangeKind.REGISTERED)
    api.advance(timedelta(hours=1))
    assert "sweep" in scheduler.tick()
    changes = [e.change for e in runner_events(api) if e.type is ChangeType.RUNNER_CHANGED]
    assert ChangeKind.OFFLINE in changes
    assert api.client.get(f"/v1/runners/{runner_id}", headers=H(api.viewer())).json()["state"] == "offline"


def test_tick_runs_each_task_only_when_due_and_is_idempotent() -> None:
    api = build_api()
    scheduler = Scheduler(api.deps)
    assert scheduler.tick() == ["sweep", "purge", "sessions"]
    assert scheduler.tick() == []
    api.advance(timedelta(seconds=31))
    assert scheduler.tick() == ["sweep"]
    api.advance(timedelta(hours=1, seconds=1))
    assert set(scheduler.tick()) == {"sweep", "sessions"}
    api.advance(timedelta(days=1, seconds=1))
    assert set(scheduler.tick()) == {"sweep", "purge", "sessions"}


def test_expired_sessions_are_deleted_after_the_retention_period() -> None:
    api = build_api()
    api.login_as("u1", ["g-member"])
    scheduler = Scheduler(api.deps)
    scheduler.tick()
    assert len(api.sessions.all()) == 1  # 有効なセッションは残る
    api.advance(timedelta(days=8))
    scheduler.run_session_cleanup()
    assert api.sessions.all() == []


def test_purge_removes_finished_jobs_past_retention() -> None:
    api = build_api()
    _runner_id, _token = api.register_runner("r-a")
    alice = api.member("alice")
    job_id = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    api.client.post(f"/v1/jobs/{job_id}/cancel", json={}, headers=H(alice))
    api.advance(timedelta(days=400))
    Scheduler(api.deps).run_purge()
    assert api.client.get(f"/v1/jobs/{job_id}", headers=H(api.member("alice"))).status_code == 404


def test_auth_failure_windows_are_finalized_by_the_scheduler() -> None:
    api = build_api()
    for _ in range(5):
        api.client.get("/v1/queue", headers=H("ss_unknown"))
    api.advance(timedelta(minutes=2))
    Scheduler(api.deps).run_session_cleanup()
    log = api.client.get("/v1/audit-log", params={"operation": "auth_failed"}, headers=H(api.admin())).json()["items"]
    assert [item["after"].get("suppressed") for item in log] == [None, 4]


def test_a_failing_task_does_not_stop_the_others() -> None:
    api = build_api()
    scheduler = Scheduler(api.deps)

    def boom() -> None:
        raise RuntimeError("x")

    scheduler._tasks["sweep"] = boom
    assert scheduler.tick() == ["purge", "sessions"]


def test_start_and_stop_run_the_loop_in_a_background_thread() -> None:
    api = build_api()
    scheduler = Scheduler(api.deps, poll_seconds=0.01)
    scheduler.start()
    scheduler.stop()
    assert "sweep" in scheduler._next
