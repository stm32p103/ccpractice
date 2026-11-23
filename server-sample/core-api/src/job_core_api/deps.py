"""API が使う依存の束(ポートと設定。憲章 原則 3)。

core-api は、ポートの実装(永続化・認証基盤)を import しない。組み立てる側(core-server、テストの build_api)が
実装を選んで ApiDependencies を作り、create_app に渡す。
"""

from __future__ import annotations

from dataclasses import dataclass

from job_core.access.permission import Permission
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application import (
    AppendLog,
    AssignNextJob,
    CancelJob,
    ConfirmStopped,
    CoreDependencies,
    GetAuditLog,
    GetJob,
    GetJobHistory,
    ListArtifacts,
    ListJobs,
    PurgeExpired,
    ReadLog,
    ReportFinished,
    RescheduleJob,
    ResolveSourceAccess,
    RetryJob,
    SearchJobs,
    SubmitJob,
)
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
    SetMaintenance,
    SweepRunners,
)

from .access.audit import AuthFailureAuditor
from .access.authenticate import Authenticator
from .access.config_reload import AccessConfigReloader
from .access.credentials import ServiceCredentials
from .access.holder import AccessConfigHolder
from .access.ports import AccessConfigSource, IdentityProvider, ServiceCredentialRepository, SessionRepository
from .access.sessions import SessionService
from .events.broker import InProcessChangeBroker
from .events.ports import ChangeBroker
from .events.publisher import ChangePublisher
from .events.sse import SseConnections
from .runner_ports import SourceCredentialIssuer
from .settings import ApiSettings


@dataclass(frozen=True)
class CoreUseCases:
    """コア(001・002)のユースケースの束。API は、これを呼ぶだけで規則を持たない。"""

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
    search_jobs: SearchJobs
    get_job: GetJob
    get_job_history: GetJobHistory
    get_audit_log: GetAuditLog
    append_log: AppendLog
    read_log: ReadLog
    list_artifacts: ListArtifacts
    resolve_source_access: ResolveSourceAccess
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

    @classmethod
    def build(cls, deps: RunnerDependencies) -> CoreUseCases:
        """ポートの束(001・002)から、ユースケースの束を作る。永続化・時計・乱数の実装は、組み立てる側が選ぶ。"""
        return cls(
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
            search_jobs=SearchJobs(deps),
            get_job=GetJob(deps),
            get_job_history=GetJobHistory(deps),
            get_audit_log=GetAuditLog(deps),
            append_log=AppendLog(deps),
            read_log=ReadLog(deps),
            list_artifacts=ListArtifacts(deps),
            resolve_source_access=ResolveSourceAccess(deps),
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
        )


@dataclass(frozen=True)
class ApiDependencies:
    """create_app に渡す依存。"""

    core: CoreUseCases
    settings: ApiSettings
    identity: IdentityProvider
    sessions: SessionRepository
    credentials: ServiceCredentialRepository
    access_source: AccessConfigSource
    access: AccessConfigHolder
    auditor: AuthFailureAuditor
    authenticator: Authenticator
    service_credentials: ServiceCredentials
    session_service: SessionService
    access_reloader: AccessConfigReloader
    broker: ChangeBroker
    publisher: ChangePublisher
    sse_connections: SseConnections
    source_credentials: SourceCredentialIssuer | None = None
    """004: ソースの取得資格の発行元。未設定なら、取得資格の要求は 422 source_not_available。"""

    @classmethod
    def assemble(
        cls,
        *,
        core: CoreUseCases,
        settings: ApiSettings,
        identity: IdentityProvider,
        sessions: SessionRepository,
        credentials: ServiceCredentialRepository,
        access_source: AccessConfigSource,
        broker: ChangeBroker | None = None,
        source_credentials: SourceCredentialIssuer | None = None,
    ) -> ApiDependencies:
        """アクセス設定を読み込み(不正なら AccessConfigInvalid)、認証の部品をつないで作る。"""
        access = AccessConfigHolder(access_source.load())
        change_broker: ChangeBroker = broker or InProcessChangeBroker(
            replay_size=settings.sse_replay_size,
            subscriber_queue=settings.sse_subscriber_queue,
            now=core.deps.clock.now,
        )
        auditor = AuthFailureAuditor(core.deps, settings)
        authenticator = Authenticator(
            deps=core.deps,
            settings=settings,
            sessions=sessions,
            credentials=credentials,
            access=access,
            authenticate_runner=core.authenticate_runner,
            auditor=auditor,
        )
        return cls(
            core=core,
            settings=settings,
            identity=identity,
            sessions=sessions,
            credentials=credentials,
            access_source=access_source,
            access=access,
            auditor=auditor,
            authenticator=authenticator,
            service_credentials=ServiceCredentials(core.deps, credentials, access),
            session_service=SessionService(
                deps=core.deps,
                settings=settings,
                identity=identity,
                sessions=sessions,
                access=access,
                auditor=auditor,
            ),
            access_reloader=AccessConfigReloader(core.deps, access_source, access),
            broker=change_broker,
            publisher=ChangePublisher(change_broker, lambda: _runner_states(core)),
            sse_connections=SseConnections(settings.sse_max_connections),
            source_credentials=source_credentials,
        )


INTERNAL_READER = Principal.of("internal-reader", [Permission.GENERAL], PrincipalKind.SYSTEM)
"""内部の状態の写しの取得用(HTTP からは使えない。通知の差分の検出)。"""


def _runner_states(core: CoreUseCases) -> dict[str, str]:
    return {str(view.runner_id): view.state.value for view in core.list_runners(INTERNAL_READER)}
