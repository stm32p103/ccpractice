"""US5 — ジョブの状態と結果の確認(spec US5-1〜US5-3 とエッジケース)。"""

from __future__ import annotations

from dataclasses import fields

import pytest

from job_core.access.permission import Permission as P
from job_core.job.application import (
    JobNotFound,
    JobState,
    JobSummaryView,
    PermissionDenied,
    Placement,
)

from .conftest import Env, principal


def test_us5_1_everyone_sees_all_jobs_in_queue_order(env: Env) -> None:
    mine = env.submit(env.alice).job_id
    others = env.submit(env.bob).job_id
    moved = env.submit(env.bob).job_id
    env.core.reschedule(env.scheduler, job_id=moved, placement=Placement.before(mine))
    running = env.submit(env.bob, requirement={"os": "y"}).job_id
    env.run(running, "R2")
    view = env.core.list_jobs(env.alice)
    assert [(s.job_id, s.owner, s.position) for s in view.queued] == [
        (moved, "bob", 1),
        (mine, "alice", 2),
        (others, "bob", 3),
    ]
    assert [s.job_id for s in view.running] == [running]
    assert view.running[0].state is JobState.RUNNING


def test_us5_2_others_job_detail_has_same_fields(env: Env) -> None:
    mine = env.submit(env.alice).job_id
    others = env.submit(env.bob).job_id
    mine_view = env.core.get_job(env.alice, job_id=mine)
    others_view = env.core.get_job(env.alice, job_id=others)
    assert [f.name for f in fields(mine_view)] == [f.name for f in fields(others_view)]
    assert others_view.summary.owner == "bob"
    assert others_view.definition.payload == {"args": ["--run"]}


def test_us5_3_seeing_does_not_grant_cancel(env: Env) -> None:
    others = env.submit(env.bob).job_id
    env.core.get_job(env.alice, job_id=others)
    with pytest.raises(PermissionDenied):
        env.core.cancel(env.alice, job_id=others)


def test_edge_list_has_no_payload_but_detail_does(env: Env) -> None:
    job_id = env.submit(payload={"secret-ish": "value"}).job_id
    names = {f.name for f in fields(JobSummaryView)}
    assert "payload" not in names and "definition" not in names
    assert env.core.get_job(env.viewer, job_id=job_id).definition.payload == {"secret-ish": "value"}


def test_edge_detail_links_retries_both_ways(env: Env) -> None:
    original = env.submit().job_id
    env.run(original)
    env.finish(original, JobState.FAILED)
    retried = env.core.retry(env.bob, job_id=original).job_id
    assert env.core.get_job(env.viewer, job_id=original).retries == (retried,)
    ref = env.core.get_job(env.viewer, job_id=retried).retry_of
    assert ref is not None and (ref.job_id, ref.exists) == (original, True)


def test_edge_unknown_job_and_view_permission(env: Env) -> None:
    with pytest.raises(JobNotFound):
        env.core.get_job(env.viewer, job_id="nope")
    no_view = principal("no-view", {P.JOB_SUBMIT})
    with pytest.raises(PermissionDenied):
        env.core.list_jobs(no_view)
    with pytest.raises(PermissionDenied):
        env.core.get_job(no_view, job_id="nope")


def test_edge_finished_jobs_are_paged_newest_first(env: Env) -> None:
    finished = []
    for _ in range(5):
        job_id = env.submit().job_id
        env.run(job_id)
        env.finish(job_id)
        finished.append(job_id)
    first = env.core.list_jobs(env.viewer, states=[JobState.SUCCEEDED], limit=2)
    second = env.core.list_jobs(env.viewer, states=[JobState.SUCCEEDED], cursor=first.next_cursor, limit=2)
    third = env.core.list_jobs(env.viewer, states=[JobState.SUCCEEDED], cursor=second.next_cursor, limit=2)
    seen = [s.job_id for page in (first, second, third) for s in page.finished]
    assert seen == list(reversed(finished))
    assert third.next_cursor is None
    assert first.queued == () and first.running == ()


def test_edge_abort_pending_is_visible(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    env.core.cancel(env.alice, job_id=job_id, reason="止めて")
    assert env.core.list_jobs(env.viewer).running[0].abort_pending
    detail = env.core.get_job(env.viewer, job_id=job_id)
    assert detail.cancellation is not None and detail.cancellation.reason == "止めて"
