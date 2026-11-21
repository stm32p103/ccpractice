"""US4 — 終了したジョブのやり直し(spec US4-1〜US4-7 とエッジケース)。"""

from __future__ import annotations

import pytest

from job_core.access.permission import Permission as P
from job_core.job.application import (
    AuditOperation,
    DuplicateQueuedJob,
    InvalidStateTransition,
    JobNotFound,
    JobState,
    NoEligibleRunner,
    PermissionDenied,
    Placement,
)
from job_core.shared.ids import JobId

from .conftest import Env, principal


def failed_job(env: Env, **overrides: object) -> str:
    job_id = env.submit(**overrides).job_id
    env.run(job_id)
    env.finish(job_id, JobState.FAILED)
    return job_id


def test_us4_1_retry_creates_new_job_at_tail_linked_both_ways(env: Env) -> None:
    original = failed_job(env, source="repo", revision="abc")
    other = env.submit().job_id
    retried = env.core.retry(env.alice, job_id=original)
    assert env.queue_ids() == [other, retried.job_id]
    new_job, old_job = env.job(retried.job_id), env.job(original)
    assert new_job.definition == old_job.definition  # 出所のリビジョンを含めて同一
    assert new_job.definition.source_ref is not None and new_job.definition.source_ref.revision == "abc"
    assert new_job.retry_of == original
    with env.core.new_uow() as uow:
        assert uow.jobs.find_retries_of(JobId(original)) == [retried.job_id]


def test_us4_2_original_job_is_not_changed(env: Env) -> None:
    original = failed_job(env)
    before = env.job(original)
    history_before = env.core.get_job_history(env.viewer, job_id=original)
    env.core.retry(env.alice, job_id=original)
    after = env.job(original)
    for name in ("state", "result_summary", "finished_at", "cancellation", "version", "definition", "submitter"):
        assert getattr(after, name) == getattr(before, name), name
    assert env.core.get_job_history(env.viewer, job_id=original) == history_before


@pytest.mark.parametrize("running", [False, True])
def test_us4_3_unfinished_job_cannot_be_retried(env: Env, running: bool) -> None:
    job_id = env.submit().job_id
    if running:
        env.run(job_id)
    with pytest.raises(InvalidStateTransition):
        env.core.retry(env.alice, job_id=job_id)


def test_us4_4_retry_rejected_when_no_runner_can_satisfy(env: Env) -> None:
    original = failed_job(env)
    env.core.runners.unregister("R1")
    with pytest.raises(NoEligibleRunner):
        env.core.retry(env.alice, job_id=original)


def test_us4_5_anyone_with_submit_permission_can_retry_others_job(env: Env) -> None:
    original = failed_job(env)
    result = env.core.retry(env.bob, job_id=original)
    new_job = env.job(result.job_id)
    assert (new_job.submitter.owner, new_job.submitter.submitted_by) == ("bob", "bob")
    assert new_job.retry_of == original
    assert env.job(original).submitter.owner == "alice"


def test_us4_6_placed_retry_requires_schedule_permission(env: Env) -> None:
    original = failed_job(env)
    b = env.submit().job_id
    with pytest.raises(PermissionDenied):
        env.core.retry(env.bob, job_id=original, placement=Placement.before(b))
    assert env.queue_ids() == [b]
    result = env.core.retry(env.scheduler, job_id=original, placement=Placement.before(b))
    assert env.queue_ids() == [result.job_id, b]
    record = env.core.get_job_history(env.viewer, job_id=result.job_id)[0]
    assert record.operation is AuditOperation.RETRY
    assert record.after["anchor"] == b and record.after["retry_of"] == original


def test_us4_7_retry_requires_submit_permission(env: Env) -> None:
    others = failed_job(env)  # alice のジョブ
    nobody = principal("nobody", {P.GENERAL})
    own = env.core.retry(env.alice, job_id=others).job_id
    env.run(own)
    env.finish(own, JobState.FAILED)
    # nobody 自身の名義のジョブを用意する(提出代行で nobody の名義にする)
    nobodys = env.submit(env.service, on_behalf_of="nobody").job_id
    env.core.cancel(nobody, job_id=nobodys)
    for target in (others, nobodys):
        with pytest.raises(PermissionDenied):
            env.core.retry(nobody, job_id=target)
    assert [r.operation for r in env.denied_records()] == [AuditOperation.RETRY, AuditOperation.RETRY]


def test_edge_retry_of_retry_can_be_traced_to_first_job(env: Env) -> None:
    first = failed_job(env)
    second = env.core.retry(env.alice, job_id=first).job_id
    env.run(second)
    env.finish(second, JobState.FAILED)
    third = env.core.retry(env.alice, job_id=second).job_id
    chain = [third]
    while (parent := env.job(chain[-1]).retry_of) is not None:
        chain.append(parent)
    assert chain == [third, second, first]


def test_edge_retry_is_rejected_when_same_content_is_queued(env: Env) -> None:
    original = failed_job(env, source="repo", revision="abc")
    queued = env.submit(env.bob, source="repo", revision="abc").job_id
    with pytest.raises(DuplicateQueuedJob) as duplicate:
        env.core.retry(env.alice, job_id=original)
    assert duplicate.value.existing_job_id == queued


def test_edge_cancelled_and_succeeded_jobs_can_be_retried(env: Env) -> None:
    cancelled = env.submit().job_id
    env.core.cancel(env.alice, job_id=cancelled)
    succeeded = env.submit().job_id
    env.run(succeeded)
    env.finish(succeeded)
    assert env.core.retry(env.alice, job_id=cancelled).position == 1
    assert env.core.retry(env.alice, job_id=succeeded).position == 2


def test_edge_retry_of_unknown_job(env: Env) -> None:
    with pytest.raises(JobNotFound):
        env.core.retry(env.alice, job_id="nope")
