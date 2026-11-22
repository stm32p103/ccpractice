"""ジョブの要求・応答のモデル(contracts/http-api.md §2.2)。

001 の JobSummaryView・JobDetailView の写し。payload は一覧の型に含めない(詳細の definition だけ)。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

from job_core.job.application import (
    CancelResult,
    JobDetailView,
    JobSearchPage,
    JobSummaryView,
    RescheduleResult,
    SubmitResult,
)
from job_core.job.application.queries.job_views import CancellationView, DefinitionView, RelatedJobRef
from job_core.job.domain.states import JobState
from job_core.job.domain.values import Placement

MAX_TIMEOUT_SECONDS = 10 * 365 * 24 * 3600


def _reject_numeric(value: Any) -> Any:
    """日時は RFC 3339 の文字列だけ。数値(UNIX 時刻として解釈される値)は受け付けない。"""
    if isinstance(value, bool | int | float):
        raise ValueError("RFC 3339 の日時でなければならない")
    if isinstance(value, str) and value.strip().lstrip("-").replace(".", "", 1).isdigit():
        raise ValueError("RFC 3339 の日時でなければならない")
    return value


RfcDatetime = Annotated[AwareDatetime, BeforeValidator(_reject_numeric)]
"""オフセットつきの RFC 3339 の日時(`2026-11-21T09:00:00Z`)。"""


class ApiModel(BaseModel):
    """応答のモデルの基底。未知の項目を受け付けない要求のモデルと区別するため、要求は strict にする。"""

    model_config = ConfigDict(extra="forbid")


class PlacementIn(ApiModel):
    """位置の指定。基準のジョブの前(before)か後(after)。"""

    anchor_job_id: str = Field(description="基準にする待機中のジョブの識別子")
    side: Literal["before", "after"]

    def to_core(self) -> Placement:
        return Placement(anchor=self.anchor_job_id, side=self.side)  # type: ignore[arg-type]


class DefinitionIn(ApiModel):
    job_type: str = Field(min_length=1, description="ジョブの種類(識別子。コアは意味を解釈しない)")
    requirement: Any = Field(description="ランナー要件")
    payload: Any = Field(description="ジョブの入力。API はこの内容を解釈しない")
    timeout_seconds: float = Field(gt=0, le=MAX_TIMEOUT_SECONDS, allow_inf_nan=False)
    source: str | None = None
    revision: str | None = None

    def timeout(self) -> timedelta:
        return timedelta(seconds=self.timeout_seconds)


class SubmitRequest(ApiModel):
    definition: DefinitionIn
    on_behalf_of: str | None = Field(default=None, description="別の提出者の名義で提出する(提出代行の権限が要る)")
    placement: PlacementIn | None = None


class RetryRequest(ApiModel):
    placement: PlacementIn | None = None


class RescheduleRequest(ApiModel):
    placement: PlacementIn


class CancelRequest(ApiModel):
    reason: str | None = Field(default=None, description="待機中は任意、実行中の強制中断は必須")


class SubmitResultOut(ApiModel):
    job_id: str
    position: int

    @classmethod
    def of(cls, result: SubmitResult) -> SubmitResultOut:
        return cls(job_id=result.job_id, position=result.position)


class RescheduleResultOut(ApiModel):
    job_id: str
    position_before: int
    position_after: int

    @classmethod
    def of(cls, result: RescheduleResult) -> RescheduleResultOut:
        return cls(job_id=result.job_id, position_before=result.position_before, position_after=result.position_after)


class CancelResultOut(ApiModel):
    job_id: str
    state: JobState
    abort_pending: bool

    @classmethod
    def of(cls, result: CancelResult) -> CancelResultOut:
        return cls(job_id=result.job_id, state=result.state, abort_pending=result.abort_pending)


class JobSummary(ApiModel):
    job_id: str
    job_type: str
    owner: str
    submitted_by: str
    state: JobState
    position: int | None
    submitted_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_summary: str | None
    abort_pending: bool
    retry_of: str | None

    @classmethod
    def of(cls, view: JobSummaryView) -> JobSummary:
        return cls(
            job_id=view.job_id,
            job_type=view.job_type,
            owner=view.owner,
            submitted_by=view.submitted_by,
            state=view.state,
            position=view.position,
            submitted_at=view.submitted_at,
            started_at=view.started_at,
            finished_at=view.finished_at,
            result_summary=view.result_summary,
            abort_pending=view.abort_pending,
            retry_of=view.retry_of,
        )


class DefinitionOut(ApiModel):
    job_type: str
    requirement: Any
    payload: Any
    timeout_seconds: float
    source: str | None
    revision: str | None

    @classmethod
    def of(cls, view: DefinitionView) -> DefinitionOut:
        return cls(
            job_type=view.job_type,
            requirement=view.requirement,
            payload=view.payload,
            timeout_seconds=view.timeout.total_seconds(),
            source=view.source,
            revision=view.revision,
        )


class CancellationOut(ApiModel):
    kind: str
    requested_by: str
    requested_at: datetime
    reason: str | None
    confirmed_at: datetime | None
    superseded_by: JobState | None

    @classmethod
    def of(cls, view: CancellationView) -> CancellationOut:
        return cls(
            kind=view.kind,
            requested_by=view.requested_by,
            requested_at=view.requested_at,
            reason=view.reason,
            confirmed_at=view.confirmed_at,
            superseded_by=view.superseded_by,
        )


class RelatedJob(ApiModel):
    job_id: str
    exists: bool

    @classmethod
    def of(cls, ref: RelatedJobRef) -> RelatedJob:
        return cls(job_id=ref.job_id, exists=ref.exists)


class JobDetail(ApiModel):
    summary: JobSummary
    definition: DefinitionOut
    cancellation: CancellationOut | None
    retry_of: RelatedJob | None
    retries: list[str]

    @classmethod
    def of(cls, view: JobDetailView) -> JobDetail:
        return cls(
            summary=JobSummary.of(view.summary),
            definition=DefinitionOut.of(view.definition),
            cancellation=CancellationOut.of(view.cancellation) if view.cancellation else None,
            retry_of=RelatedJob.of(view.retry_of) if view.retry_of else None,
            retries=list(view.retries),
        )


class JobPage(ApiModel):
    items: list[JobSummary]
    next_cursor: str | None = Field(description="次の頁の cursor。null なら最後")

    @classmethod
    def of(cls, page: JobSearchPage) -> JobPage:
        return cls(items=[JobSummary.of(item) for item in page.items], next_cursor=page.next_cursor)


class QueueOut(ApiModel):
    items: list[JobSummary] = Field(description="待機中の全件。待機列の順序(position は 1 から)")

    @classmethod
    def of(cls, items: tuple[JobSummaryView, ...]) -> QueueOut:
        return cls(items=[JobSummary.of(item) for item in items])
