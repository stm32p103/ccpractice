"""core のポートのメモリ上の Fake と、Fake をつないだユースケースの集合(quickstart.md §4)。"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.job.application import (
    AssignNextJob,
    CancelJob,
    ConfirmStopped,
    CoreDependencies,
    GetAuditLog,
    GetJob,
    GetJobHistory,
    ListJobs,
    PurgeExpired,
    ReportFinished,
    RescheduleJob,
    RetryJob,
    SubmitJob,
)

from .clock_ids import FakeClock, SequentialIdGenerator
from .repositories import InMemoryStore, InMemoryUnitOfWork
from .runners import FakeRunnerEligibility

__all__ = [
    "CoreFixture",
    "FakeClock",
    "FakeRunnerEligibility",
    "InMemoryStore",
    "InMemoryUnitOfWork",
    "SequentialIdGenerator",
    "build_core",
]


@dataclass
class CoreFixture:
    """Fake をつないだユースケースの集合。"""

    store: InMemoryStore
    runners: FakeRunnerEligibility
    clock: FakeClock
    ids: SequentialIdGenerator
    deps: CoreDependencies
    submit: SubmitJob
    reschedule: RescheduleJob
    cancel: CancelJob
    retry: RetryJob
    assign: AssignNextJob
    report_finished: ReportFinished
    confirm_stopped: ConfirmStopped
    purge: PurgeExpired
    list_jobs: ListJobs
    get_job: GetJob
    get_job_history: GetJobHistory
    get_audit_log: GetAuditLog

    def new_uow(self) -> InMemoryUnitOfWork:
        return self.store.new_unit_of_work()


def build_core(*, max_conflict_retries: int = 3) -> CoreFixture:
    store = InMemoryStore()
    runners = FakeRunnerEligibility()
    clock = FakeClock()
    ids = SequentialIdGenerator()
    deps = CoreDependencies(
        uow_factory=store.new_unit_of_work,
        eligibility=runners,
        clock=clock,
        ids=ids,
        max_conflict_retries=max_conflict_retries,
    )
    return CoreFixture(
        store=store,
        runners=runners,
        clock=clock,
        ids=ids,
        deps=deps,
        submit=SubmitJob(deps),
        reschedule=RescheduleJob(deps),
        cancel=CancelJob(deps),
        retry=RetryJob(deps),
        assign=AssignNextJob(deps),
        report_finished=ReportFinished(deps),
        confirm_stopped=ConfirmStopped(deps),
        purge=PurgeExpired(deps),
        list_jobs=ListJobs(deps),
        get_job=GetJob(deps),
        get_job_history=GetJobHistory(deps),
        get_audit_log=GetAuditLog(deps),
    )
