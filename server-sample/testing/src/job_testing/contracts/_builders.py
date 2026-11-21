"""契約テストで使う集約の組み立て。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_core.job.domain.definition import JobDefinition, Submitter
from job_core.job.domain.job import Job
from job_core.job.domain.states import JobState
from job_core.job.domain.values import Reason, ResultSummary
from job_core.shared.ids import JobId, RunnerId, SubjectId

T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def make_job(
    job_id: str,
    *,
    at: datetime = T0,
    source: str | None = None,
    revision: str | None = None,
    job_type: str = "type-a",
    owner: str = "alice",
    retry_of: str | None = None,
) -> Job:
    definition = JobDefinition.create(
        job_type=job_type,
        requirement={"os": "x"},
        payload={"args": ["--flag"], "n": 1},
        timeout=timedelta(minutes=10),
        source=source,
        revision=revision,
    )
    return Job.submit(
        job_id=JobId(job_id),
        definition=definition,
        submitter=Submitter(SubjectId(owner), SubjectId(owner)),
        at=at,
        retry_of=JobId(retry_of) if retry_of else None,
    )


def finish(job: Job, state: JobState, at: datetime, runner: str = "r1", event_id: str | None = None) -> Job:
    """job を終了状態にする(テスト用)。"""
    event = event_id or f"ev-{job.job_id}"
    if state is JobState.CANCELLED:
        job.cancel_queued(by=SubjectId("ops"), reason=Reason("不要"), at=at, event_id=event)
        return job
    job.assign(RunnerId(runner), at)
    job.finish(runner_id=RunnerId(runner), outcome=state, summary=ResultSummary("done"), at=at, event_id=event)
    return job
