"""US6 — 状態変更の記録(spec US6-1〜US6-4、SC-007)。"""

from __future__ import annotations

import pytest

from job_core.job.application import (
    AuditOperation,
    AuditOutcome,
    JobState,
    PermissionDenied,
    Placement,
    RetentionPolicy,
)

from .conftest import Env


def run_every_state_changing_operation(env: Env) -> dict[AuditOperation, str | None]:
    """data-model.md §4 の状態を変える操作をすべて 1 回ずつ行い、対象のジョブを返す。"""
    targets: dict[AuditOperation, str | None] = {}
    a = env.submit().job_id
    targets[AuditOperation.SUBMIT] = a
    placed = env.submit(env.scheduler, placement=Placement.before(a)).job_id
    targets[AuditOperation.SUBMIT_PLACED] = placed
    env.core.reschedule(env.scheduler, job_id=a, placement=Placement.before(placed))
    targets[AuditOperation.RESCHEDULE] = a
    env.core.cancel(env.scheduler, job_id=placed)
    targets[AuditOperation.CANCEL_QUEUED] = placed
    env.run(a)
    targets[AuditOperation.ASSIGN] = a
    env.core.cancel(env.alice, job_id=a, reason="止めて")
    targets[AuditOperation.ABORT_REQUEST] = a
    env.core.confirm_stopped(env.runner1, runner_id="R1", job_id=a)
    targets[AuditOperation.ABORT_CONFIRM] = a
    retried = env.core.retry(env.alice, job_id=a).job_id
    targets[AuditOperation.RETRY] = retried
    env.run(retried)
    env.finish(retried)
    targets[AuditOperation.COMPLETE] = retried
    env.core.purge(env.purger, policy=RetentionPolicy())
    targets[AuditOperation.PURGE] = None
    return targets


EXPECTED_KEYS = {
    AuditOperation.SUBMIT: (set(), {"state", "position", "retry_of"}),
    AuditOperation.SUBMIT_PLACED: (set(), {"state", "position", "anchor", "side"}),
    AuditOperation.RETRY: (set(), {"state", "position", "retry_of"}),
    AuditOperation.RESCHEDULE: ({"position"}, {"position", "anchor", "side"}),
    AuditOperation.CANCEL_QUEUED: ({"state", "position"}, {"state"}),
    AuditOperation.ABORT_REQUEST: ({"state"}, {"state", "abort_requested"}),
    AuditOperation.ABORT_CONFIRM: ({"state"}, {"state"}),
    AuditOperation.ASSIGN: ({"state", "position"}, {"state", "runner_id"}),
    AuditOperation.COMPLETE: ({"state"}, {"state"}),
    AuditOperation.PURGE: (set(), {"jobs_deleted", "audit_records_deleted", "cutoffs"}),
}


def test_us6_1_every_state_changing_operation_is_audited(env: Env) -> None:
    targets = run_every_state_changing_operation(env)
    records = env.core.get_audit_log(env.admin, outcome=AuditOutcome.SUCCEEDED, limit=1000).items
    assert set(targets) == set(EXPECTED_KEYS)
    for operation, job_id in targets.items():
        matching = [r for r in records if r.operation is operation and r.job_id == job_id]
        assert len(matching) == 1, operation
        record = matching[0]
        before_keys, after_keys = EXPECTED_KEYS[operation]
        assert set(record.before) == before_keys, operation
        assert set(record.after) == after_keys, operation
        assert record.actor and record.occurred_at
        assert "payload" not in record.before and "payload" not in record.after
    abort = next(r for r in records if r.operation is AuditOperation.ABORT_REQUEST)
    assert abort.reason == "止めて"


def test_us6_2_full_audit_log_requires_admin_permission(env: Env) -> None:
    with pytest.raises(PermissionDenied):
        env.core.get_audit_log(env.alice)
    page = env.core.get_audit_log(env.admin, outcome=AuditOutcome.DENIED)
    assert [(r.operation, r.actor) for r in page.items] == [(AuditOperation.READ_AUDIT_LOG, "alice")]


def test_us6_3_owner_sees_who_moved_their_job(env: Env) -> None:
    mine = env.submit(env.alice).job_id
    other = env.submit(env.bob).job_id
    env.core.reschedule(env.scheduler, job_id=mine, placement=Placement.after(other))
    history = env.core.get_job_history(env.alice, job_id=mine)
    move = history[-1]
    assert (move.operation, move.actor, move.before, move.after["position"]) == (
        AuditOperation.RESCHEDULE,
        "sched",
        {"position": 1},
        2,
    )
    assert env.core.get_job_history(env.alice, job_id=other)[0].operation is AuditOperation.SUBMIT


def test_us6_4_denied_operations_are_not_in_job_history(env: Env) -> None:
    mine = env.submit(env.alice).job_id
    with pytest.raises(PermissionDenied):
        env.core.cancel(env.bob, job_id=mine)
    history = env.core.get_job_history(env.alice, job_id=mine)
    assert [r.outcome for r in history] == [AuditOutcome.SUCCEEDED]
    denied = env.core.get_audit_log(env.admin, job_id=mine, outcome=AuditOutcome.DENIED).items
    assert [(r.operation, r.actor, r.denial_code) for r in denied] == [
        (AuditOperation.CANCEL_QUEUED, "bob", "permission_denied")
    ]


def test_edge_audit_log_filters_and_pages(env: Env) -> None:
    for _ in range(3):
        env.submit()
    first = env.core.get_audit_log(env.admin, operation=AuditOperation.SUBMIT, limit=2)
    second = env.core.get_audit_log(env.admin, operation="submit", cursor=first.next_cursor, limit=2)
    assert len(first.items) == 2 and len(second.items) == 1 and second.next_cursor is None
    assert all(r.operation is AuditOperation.SUBMIT for r in first.items + second.items)


def test_edge_completion_state_in_history(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    env.finish(job_id, JobState.FAILED)
    assert env.core.get_job_history(env.viewer, job_id=job_id)[-1].after == {"state": "failed"}
