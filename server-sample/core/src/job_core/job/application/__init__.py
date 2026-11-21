"""job コンテキストのアプリケーション層の公開 API(contracts/application-api.md)。

呼び出し元(003 など)は、ここで公開する名前だけを使う。
"""

from __future__ import annotations

from job_core.access.permission import Permission
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.domain.audit import AuditOperation, AuditOutcome
from job_core.job.domain.errors import (
    AbortAlreadyRequested,
    AnchorNotQueued,
    ConcurrencyConflict,
    DuplicateQueuedJob,
    InvalidStateTransition,
    JobNotFound,
    NoEligibleRunner,
    PermissionDenied,
    ReasonRequired,
    RunnerBusy,
    RunnerMismatch,
    SelfAnchor,
    TargetNotQueued,
    ValidationFailed,
)
from job_core.job.domain.events import JobCompleted
from job_core.job.domain.retention import RetentionPolicy
from job_core.job.domain.states import JobState
from job_core.job.domain.values import Placement, PlacementSide
from job_core.shared.errors import JobCoreError

from .commands.assign import AssignNextJob, AssignResult
from .commands.cancel import CancelJob, CancelResult
from .commands.confirm_stopped import ConfirmStopped
from .commands.purge import PurgeExpired, PurgeResult
from .commands.report_finished import FinishResult, ReportFinished
from .commands.reschedule import RescheduleJob, RescheduleResult
from .commands.retry import RetryJob
from .commands.submit import SubmitJob, SubmitResult
from .ports import (
    AuditFilter,
    AuditLog,
    CoreDependencies,
    JobRepository,
    Outbox,
    OutboxEntry,
    OutboxStatus,
    Page,
    QueueRepository,
    RunnerEligibility,
    UnitOfWork,
    UnitOfWorkFactory,
)
from .queries.audit_views import AuditLogPage, AuditRecordView
from .queries.get_audit_log import GetAuditLog
from .queries.get_job import GetJob
from .queries.get_job_history import GetJobHistory
from .queries.job_views import (
    CancellationView,
    DefinitionView,
    JobDetailView,
    JobListView,
    JobSummaryView,
    RelatedJobRef,
)
from .queries.list_jobs import ListJobs

__all__ = [
    "AbortAlreadyRequested",
    "AnchorNotQueued",
    "AssignNextJob",
    "AssignResult",
    "AuditFilter",
    "AuditLog",
    "AuditLogPage",
    "AuditOperation",
    "AuditOutcome",
    "AuditRecordView",
    "CancelJob",
    "CancelResult",
    "CancellationView",
    "ConcurrencyConflict",
    "ConfirmStopped",
    "CoreDependencies",
    "DefinitionView",
    "DuplicateQueuedJob",
    "FinishResult",
    "GetAuditLog",
    "GetJob",
    "GetJobHistory",
    "InvalidStateTransition",
    "JobCompleted",
    "JobCoreError",
    "JobDetailView",
    "JobListView",
    "JobNotFound",
    "JobRepository",
    "JobState",
    "JobSummaryView",
    "ListJobs",
    "NoEligibleRunner",
    "Outbox",
    "OutboxEntry",
    "OutboxStatus",
    "Page",
    "Permission",
    "PermissionDenied",
    "Placement",
    "PlacementSide",
    "Principal",
    "PrincipalKind",
    "PurgeExpired",
    "PurgeResult",
    "QueueRepository",
    "ReasonRequired",
    "RelatedJobRef",
    "ReportFinished",
    "RescheduleJob",
    "RescheduleResult",
    "RetentionPolicy",
    "RetryJob",
    "RunnerBusy",
    "RunnerEligibility",
    "RunnerMismatch",
    "SelfAnchor",
    "SubmitJob",
    "SubmitResult",
    "TargetNotQueued",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "ValidationFailed",
]
