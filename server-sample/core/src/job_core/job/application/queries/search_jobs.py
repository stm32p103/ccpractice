"""SearchJobs — 履歴の検索(003 research.md R8。状態・提出者・提出日時の範囲の絞り込み、キーセットの頁送り)。

権限は `job.general`(一覧と同じ)。payload を含まない JobSummaryView で返す。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from job_core.access.principal import Principal
from job_core.job.domain.errors import ValidationFailed
from job_core.job.domain.states import JobState
from job_core.shared.ids import SubjectId

from ..authorization import authorize_view
from ..ports import CoreDependencies, JobSearchCriteria
from .job_views import JobSummaryView

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True)
class JobSearchPage:
    items: tuple[JobSummaryView, ...]
    next_cursor: str | None


class SearchJobs:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(
        self,
        principal: Principal,
        *,
        states: Iterable[JobState | str] | None = None,
        owner: str | None = None,
        submitted_from: datetime | None = None,
        submitted_to: datetime | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> JobSearchPage:
        authorize_view(principal)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
            raise ValidationFailed("limit", f"1〜{MAX_LIMIT} でなければならない")
        try:
            wanted = frozenset(JobState(s) for s in states) if states is not None else None
        except ValueError:
            raise ValidationFailed("states", "未知の状態") from None
        criteria = JobSearchCriteria(
            states=wanted,
            owner=SubjectId(owner) if owner is not None else None,
            submitted_from=submitted_from,
            submitted_to=submitted_to,
        )
        with self._deps.uow_factory() as uow:
            page = uow.jobs.search(criteria, cursor, limit)
            queue = uow.queue.get()
            positions = {job_id: position for position, job_id in enumerate(queue.entries, start=1)}
            items = tuple(
                JobSummaryView.of(job, positions.get(job.job_id) if job.state is JobState.QUEUED else None)
                for job in page.items
            )
        return JobSearchPage(items=items, next_cursor=page.next_cursor)
