"""同時の提出の競合(spec Edge Cases。Fake のコミット直前のフックで決定的に再現する)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.job.application import ConcurrencyConflict, DuplicateQueuedJob, JobState
from job_core.job.application.commands.submit import SubmitJob
from job_core.job.application.ports import CoreDependencies
from job_testing.core_fakes import InMemoryUnitOfWork

from .conftest import Env


def test_concurrency_duplicate_submissions_only_one_is_accepted(env: Env) -> None:
    accepted: list[str] = []

    def concurrent_submit() -> None:
        accepted.append(env.submit(env.bob, source="repo", revision="abc").job_id)

    env.core.store.inject_before_next_commit(concurrent_submit)
    with pytest.raises(DuplicateQueuedJob) as duplicate:
        env.submit(source="repo", revision="abc")
    assert duplicate.value.existing_job_id == accepted[0]
    assert env.queue_ids() == accepted
    env.assert_consistent()


def test_concurrency_submit_and_assign_keep_queue_consistent(env: Env) -> None:
    first = env.submit().job_id
    assigned: list[str | None] = []
    env.core.store.inject_before_next_commit(lambda: assigned.append(env.assign()))
    second = env.submit().job_id
    assert assigned == [first]
    assert env.queue_ids() == [second]
    assert env.job(first).state is JobState.RUNNING
    env.assert_consistent()


class _AlwaysConflictingUnitOfWork(InMemoryUnitOfWork):
    attempts = 0

    def commit(self) -> None:
        type(self).attempts += 1
        raise ConcurrencyConflict("常に衝突する")


def test_concurrency_conflict_is_reported_after_retries_are_exhausted(env: Env) -> None:
    store = env.core.store
    deps = CoreDependencies(
        uow_factory=lambda: _AlwaysConflictingUnitOfWork(store),
        eligibility=env.core.runners,
        clock=env.core.clock,
        ids=env.core.ids,
        max_conflict_retries=3,
    )
    _AlwaysConflictingUnitOfWork.attempts = 0
    with pytest.raises(ConcurrencyConflict):
        SubmitJob(deps)(env.alice, job_type="t", requirement={"os": "x"}, payload={}, timeout=timedelta(minutes=1))
    assert _AlwaysConflictingUnitOfWork.attempts == 3
    assert env.queue_ids() == []
