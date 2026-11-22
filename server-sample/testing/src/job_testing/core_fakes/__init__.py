"""core のポートのメモリ上の Fake と、Fake をつないだユースケースの集合(quickstart.md §4)。

build_core() は 001 のユースケースに加え、002 のランナー管理のユースケースも含む。
既定では、ランナーの判定(RunnerEligibility)に 001 のテスト用の FakeRunnerEligibility を使う
(001 の受け入れテストが使う要件の形 {"キー": "値"} のまま動かすため)。
use_runner_management=True にすると、002 の RunnerEligibilityService に切り替える(002 の受け入れテスト、quickstart)。
"""

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
    SearchJobs,
    SubmitJob,
)
from job_core.job.application.ports import RunnerEligibility
from job_core.runner.application import (
    AuthenticateRunner,
    ClearFault,
    ClearMaintenance,
    CreateRunner,
    DeleteRunner,
    GetCapabilityAllowlist,
    GetRunner,
    GetRunnerHistory,
    Heartbeat,
    ListRunners,
    RegisterRunner,
    ReissueToken,
    ReplaceCapabilityAllowlist,
    ReportFault,
    ReportRecovered,
    RequestJob,
    RevokeToken,
    RunnerDependencies,
    RunnerEligibilityService,
    RunnerTimingPolicy,
    SetMaintenance,
    SweepRunners,
)

from .clock_ids import FakeClock, FakeSecretGenerator, SequentialIdGenerator
from .repositories import InMemoryStore, InMemoryUnitOfWork
from .runner_repositories import InMemoryRunnerCatalog
from .runners import FakeRunnerEligibility

__all__ = [
    "CoreFixture",
    "FakeClock",
    "FakeRunnerEligibility",
    "FakeSecretGenerator",
    "InMemoryRunnerCatalog",
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
    deps: RunnerDependencies
    submit: SubmitJob
    reschedule: RescheduleJob
    cancel: CancelJob
    retry: RetryJob
    assign: AssignNextJob
    report_finished: ReportFinished
    confirm_stopped: ConfirmStopped
    purge: PurgeExpired
    list_jobs: ListJobs
    search_jobs: SearchJobs
    get_job: GetJob
    get_job_history: GetJobHistory
    get_audit_log: GetAuditLog
    # --- 002 ランナー管理 ---
    create_runner: CreateRunner
    replace_allowlist: ReplaceCapabilityAllowlist
    get_allowlist: GetCapabilityAllowlist
    authenticate_runner: AuthenticateRunner
    register_runner: RegisterRunner
    heartbeat: Heartbeat
    report_fault: ReportFault
    report_recovered: ReportRecovered
    clear_fault: ClearFault
    set_maintenance: SetMaintenance
    clear_maintenance: ClearMaintenance
    delete_runner: DeleteRunner
    reissue_token: ReissueToken
    revoke_token: RevokeToken
    request_job: RequestJob
    sweep_runners: SweepRunners
    list_runners: ListRunners
    get_runner: GetRunner
    get_runner_history: GetRunnerHistory
    runner_eligibility: RunnerEligibilityService

    def new_uow(self) -> InMemoryUnitOfWork:
        return self.store.new_unit_of_work()


def build_core(
    *,
    max_conflict_retries: int = 3,
    use_runner_management: bool = False,
    timing: RunnerTimingPolicy | None = None,
) -> CoreFixture:
    store = InMemoryStore()
    fake_runners = FakeRunnerEligibility()
    clock = FakeClock()
    ids = SequentialIdGenerator()
    catalog = InMemoryRunnerCatalog(store.runner_state, store.lock)
    runner_eligibility = RunnerEligibilityService(catalog)
    eligibility: RunnerEligibility = runner_eligibility if use_runner_management else fake_runners
    deps = RunnerDependencies(
        uow_factory=store.new_unit_of_work,
        eligibility=eligibility,
        clock=clock,
        ids=ids,
        max_conflict_retries=max_conflict_retries,
        catalog=catalog,
        secrets=FakeSecretGenerator(),
        timing=timing or RunnerTimingPolicy(),
    )
    core_deps: CoreDependencies = deps
    return CoreFixture(
        store=store,
        runners=fake_runners,
        clock=clock,
        ids=ids,
        deps=deps,
        submit=SubmitJob(core_deps),
        reschedule=RescheduleJob(core_deps),
        cancel=CancelJob(core_deps),
        retry=RetryJob(core_deps),
        assign=AssignNextJob(core_deps),
        report_finished=ReportFinished(core_deps),
        confirm_stopped=ConfirmStopped(core_deps),
        purge=PurgeExpired(core_deps),
        list_jobs=ListJobs(core_deps),
        search_jobs=SearchJobs(core_deps),
        get_job=GetJob(core_deps),
        get_job_history=GetJobHistory(core_deps),
        get_audit_log=GetAuditLog(core_deps),
        create_runner=CreateRunner(deps),
        replace_allowlist=ReplaceCapabilityAllowlist(deps),
        get_allowlist=GetCapabilityAllowlist(deps),
        authenticate_runner=AuthenticateRunner(deps),
        register_runner=RegisterRunner(deps),
        heartbeat=Heartbeat(deps),
        report_fault=ReportFault(deps),
        report_recovered=ReportRecovered(deps),
        clear_fault=ClearFault(deps),
        set_maintenance=SetMaintenance(deps),
        clear_maintenance=ClearMaintenance(deps),
        delete_runner=DeleteRunner(deps),
        reissue_token=ReissueToken(deps),
        revoke_token=RevokeToken(deps),
        request_job=RequestJob(deps),
        sweep_runners=SweepRunners(deps),
        list_runners=ListRunners(deps),
        get_runner=GetRunner(deps),
        get_runner_history=GetRunnerHistory(deps),
        runner_eligibility=runner_eligibility,
    )
