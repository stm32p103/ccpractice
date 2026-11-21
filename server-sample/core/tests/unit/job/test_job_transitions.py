"""状態遷移(data-model.md「JobState と遷移表」の全行)。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from job_core.job.domain.definition import JobDefinition, Submitter
from job_core.job.domain.errors import (
    AbortAlreadyRequested,
    InvalidStateTransition,
    ReasonRequired,
    RunnerMismatch,
)
from job_core.job.domain.events import JobCompleted
from job_core.job.domain.job import CancellationKind, Job
from job_core.job.domain.states import JobState
from job_core.job.domain.values import Reason, ResultSummary
from job_core.shared.ids import JobId, RunnerId, SubjectId

T0 = datetime(2026, 1, 1, tzinfo=UTC)
R1 = RunnerId("r1")
R2 = RunnerId("r2")
ALICE = SubjectId("alice")
OPS = SubjectId("ops")


def new_job() -> Job:
    definition = JobDefinition.create(job_type="t", requirement={}, payload={}, timeout=timedelta(minutes=1))
    return Job.submit(job_id=JobId("j1"), definition=definition, submitter=Submitter(ALICE, ALICE), at=T0)


def running_job(*, abort: bool = False) -> Job:
    job = new_job()
    job.assign(R1, T0)
    if abort:
        job.request_abort(by=OPS, reason=Reason("stop"), at=T0)
    return job


def finished_job(state: JobState) -> Job:
    if state is JobState.CANCELLED:
        job = new_job()
        job.cancel_queued(by=ALICE, reason=None, at=T0, event_id="e0")
    else:
        job = running_job()
        job.finish(runner_id=R1, outcome=state, summary=None, at=T0, event_id="e0")
    job.pull_events()
    return job


Operation = Callable[[Job], None]

OPERATIONS: dict[str, Operation] = {
    "assign": lambda j: j.assign(R1, T0),
    "cancel_queued": lambda j: j.cancel_queued(by=ALICE, reason=None, at=T0, event_id="e"),
    "request_abort": lambda j: j.request_abort(by=OPS, reason=Reason("x"), at=T0),
    "confirm_stopped": lambda j: j.confirm_stopped(runner_id=R1, at=T0, event_id="e"),
    "finish": lambda j: j.finish(runner_id=R1, outcome=JobState.SUCCEEDED, summary=None, at=T0, event_id="e"),
}


def test_new_job_is_queued() -> None:
    job = new_job()
    assert job.state is JobState.QUEUED
    assert job.assigned_runner_id is None
    assert job.pull_events() == []


def test_assign_moves_to_running() -> None:
    job = new_job()
    job.assign(R1, T0 + timedelta(seconds=1))
    assert job.state is JobState.RUNNING
    assert job.assigned_runner_id == R1
    assert job.started_at == T0 + timedelta(seconds=1)


def test_cancel_queued_finishes_with_cancelled_and_emits_event() -> None:
    job = new_job()
    job.cancel_queued(by=ALICE, reason=None, at=T0, event_id="e1")
    assert job.state is JobState.CANCELLED
    assert job.finished_at == T0
    assert job.cancellation is not None
    assert job.cancellation.kind is CancellationKind.QUEUED_CANCEL
    assert job.cancellation.confirmed_at == T0
    events = job.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], JobCompleted)
    assert events[0].state is JobState.CANCELLED
    assert job.pull_events() == []


def test_request_abort_keeps_running_and_records_request() -> None:
    job = running_job()
    job.request_abort(by=OPS, reason=Reason("why"), at=T0)
    assert job.state is JobState.RUNNING
    assert job.abort_pending
    assert job.cancellation is not None
    assert job.cancellation.kind is CancellationKind.FORCE_ABORT
    assert job.cancellation.confirmed_at is None
    assert job.pull_events() == []


def test_request_abort_requires_reason() -> None:
    with pytest.raises(ReasonRequired):
        running_job().request_abort(by=OPS, reason=None, at=T0)


def test_request_abort_twice_is_rejected_and_keeps_first() -> None:
    job = running_job(abort=True)
    first = job.cancellation
    with pytest.raises(AbortAlreadyRequested):
        job.request_abort(by=ALICE, reason=Reason("again"), at=T0 + timedelta(seconds=5))
    assert job.cancellation == first


def test_confirm_stopped_after_request() -> None:
    job = running_job(abort=True)
    job.confirm_stopped(runner_id=R1, at=T0 + timedelta(seconds=2), event_id="e2")
    assert job.state is JobState.CANCELLED
    assert job.cancellation is not None
    assert job.cancellation.confirmed_at == T0 + timedelta(seconds=2)
    assert [e.state for e in job.pull_events()] == [JobState.CANCELLED]


def test_confirm_stopped_without_request_is_invalid() -> None:
    job = running_job()
    with pytest.raises(InvalidStateTransition):
        job.confirm_stopped(runner_id=R1, at=T0, event_id="e")
    assert job.state is JobState.RUNNING


@pytest.mark.parametrize("outcome", [JobState.SUCCEEDED, JobState.FAILED])
def test_finish(outcome: JobState) -> None:
    job = running_job()
    job.finish(runner_id=R1, outcome=outcome, summary=ResultSummary("ok"), at=T0, event_id="e3")
    assert job.state is outcome
    assert job.result_summary == ResultSummary("ok")
    assert job.cancellation is None
    events = job.pull_events()
    assert len(events) == 1
    assert events[0].state is outcome
    assert events[0].submitter_id == ALICE


@pytest.mark.parametrize("outcome", [JobState.SUCCEEDED, JobState.FAILED])
def test_finish_after_abort_request_supersedes(outcome: JobState) -> None:
    job = running_job(abort=True)
    job.finish(runner_id=R1, outcome=outcome, summary=None, at=T0, event_id="e4")
    assert job.state is outcome
    assert job.cancellation is not None
    assert job.cancellation.superseded_by is outcome
    assert job.cancellation.confirmed_at is None
    assert len(job.pull_events()) == 1


@pytest.mark.parametrize("name", ["finish", "confirm_stopped"])
def test_report_from_other_runner_is_rejected_without_change(name: str) -> None:
    job = running_job(abort=True)
    with pytest.raises(RunnerMismatch):
        if name == "finish":
            job.finish(runner_id=R2, outcome=JobState.SUCCEEDED, summary=None, at=T0, event_id="e")
        else:
            job.confirm_stopped(runner_id=R2, at=T0, event_id="e")
    assert job.state is JobState.RUNNING
    assert job.abort_pending
    assert job.pull_events() == []


@pytest.mark.parametrize("state", [JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED])
@pytest.mark.parametrize("name", list(OPERATIONS))
def test_terminal_states_reject_every_operation(state: JobState, name: str) -> None:
    job = finished_job(state)
    before = (job.state, job.finished_at, job.cancellation, job.result_summary)
    with pytest.raises((InvalidStateTransition, RunnerMismatch)):
        OPERATIONS[name](job)
    assert (job.state, job.finished_at, job.cancellation, job.result_summary) == before
    assert job.pull_events() == []


@pytest.mark.parametrize("name", ["assign", "cancel_queued"])
def test_running_rejects_queued_only_operations(name: str) -> None:
    job = running_job()
    with pytest.raises(InvalidStateTransition):
        OPERATIONS[name](job)
    assert job.state is JobState.RUNNING


@pytest.mark.parametrize("name", ["request_abort", "finish", "confirm_stopped"])
def test_queued_rejects_running_only_operations(name: str) -> None:
    job = new_job()
    with pytest.raises(InvalidStateTransition):
        OPERATIONS[name](job)
    assert job.state is JobState.QUEUED


def test_completed_event_carries_reference_fields_only() -> None:
    job = new_job()
    job.retry_of = JobId("j0")
    job.cancel_queued(by=ALICE, reason=None, at=T0, event_id="e9")
    event = job.pull_events()[0]
    assert event.to_dict() == {
        "event_id": "e9",
        "event_type": "job.completed",
        "schema_version": 1,
        "occurred_at": "2026-01-01T00:00:00Z",
        "job_id": "j1",
        "state": "cancelled",
        "finished_at": "2026-01-01T00:00:00Z",
        "retry_of": "j0",
        "submitter_id": "alice",
    }
