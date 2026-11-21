"""GetJob — 詳細(US5。contracts/application-api.md「GetJob」)。"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.errors import JobNotFound
from job_core.shared.ids import JobId

from ..authorization import authorize_view
from ..ports import CoreDependencies
from .job_views import JobDetailView, JobSummaryView, RelatedJobRef, cancellation_view, definition_view


class GetJob:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, job_id: str) -> JobDetailView:
        authorize_view(principal)
        target = JobId(job_id)
        with self._deps.uow_factory() as uow:
            job = uow.jobs.get(target)
            if job is None:
                raise JobNotFound(target)
            position = uow.queue.get().position_of(target)
            retry_of = RelatedJobRef(job.retry_of, uow.jobs.exists(job.retry_of)) if job.retry_of else None
            retries = tuple(uow.jobs.find_retries_of(target))
            return JobDetailView(
                summary=JobSummaryView.of(job, position),
                definition=definition_view(job),
                cancellation=cancellation_view(job),
                retry_of=retry_of,
                retries=retries,
            )
