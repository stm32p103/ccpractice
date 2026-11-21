"""ListJobs — 一覧(US5、FR-022。contracts/application-api.md「ListJobs」)。"""

from __future__ import annotations

from collections.abc import Iterable

from job_core.access.principal import Principal
from job_core.job.domain.states import TERMINAL_STATES, JobState

from ..authorization import authorize_view
from ..ports import CoreDependencies
from .job_views import JobListView, JobSummaryView

DEFAULT_LIMIT = 100


class ListJobs:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(
        self,
        principal: Principal,
        *,
        states: Iterable[JobState | str] | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> JobListView:
        authorize_view(principal)
        wanted = {JobState(s) for s in states} if states is not None else set(JobState)
        with self._deps.uow_factory() as uow:
            queue = uow.queue.get()
            queued: tuple[JobSummaryView, ...] = ()
            if JobState.QUEUED in wanted:
                by_id = {job.job_id: job for job in uow.jobs.list_by_states([JobState.QUEUED], None, None).items}
                queued = tuple(
                    JobSummaryView.of(by_id[job_id], position)
                    for position, job_id in enumerate(queue.entries, start=1)
                    if job_id in by_id
                )
            running: tuple[JobSummaryView, ...] = ()
            if JobState.RUNNING in wanted:
                running = tuple(
                    JobSummaryView.of(job, None)
                    for job in uow.jobs.list_by_states([JobState.RUNNING], None, None).items
                )
            finished: tuple[JobSummaryView, ...] = ()
            next_cursor = None
            terminal = wanted & TERMINAL_STATES
            if terminal:
                page = uow.jobs.list_by_states(sorted(terminal), cursor, limit)
                finished = tuple(JobSummaryView.of(job, None) for job in page.items)
                next_cursor = page.next_cursor
        return JobListView(queued=queued, running=running, finished=finished, next_cursor=next_cursor)
