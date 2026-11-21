"""runner コンテキストのアプリケーション層の公開 API(contracts/application-api.md)。

呼び出し元(003 など)は、ここで公開する名前だけを使う。
"""

from __future__ import annotations

from job_core.runner.domain.errors import (
    AlreadyInMaintenance,
    DuplicateRunnerName,
    InvalidDeclaration,
    InvalidLeaseTransition,
    InvalidRequirement,
    LeaseExpired,
    NotInMaintenance,
    RunnerAuthenticationFailed,
    RunnerDeleted,
    RunnerHasUnfinishedJob,
    RunnerIdentityMismatch,
    RunnerNotFound,
    RunnerNotRegistered,
)
from job_core.runner.domain.lease import LeaseStatus
from job_core.runner.domain.runner import RunnerState
from job_core.runner.domain.token import IssuedToken
from job_core.runner.domain.values import InvalidTimingPolicy, RunnerTimingPolicy, ValueKind

from .commands.allowlist import ReplaceCapabilityAllowlist
from .commands.authenticate import AuthenticateRunner
from .commands.create import CreateRunner
from .commands.delete import DeleteRunner
from .commands.fault import ClearFault, ReportFault, ReportRecovered
from .commands.heartbeat import Heartbeat
from .commands.maintenance import ClearMaintenance, SetMaintenance
from .commands.register import RegisterRunner
from .commands.request_job import RequestJob
from .commands.sweep import SweepRunners
from .commands.token import ReissueToken, RevokeToken
from .eligibility import RunnerEligibilityService
from .ports import (
    CapabilityAllowlistRepository,
    LeaseRepository,
    RunnerCatalog,
    RunnerDependencies,
    RunnerRepository,
    RunnerTokenRepository,
    RunnerUnitOfWork,
    RunnerUnitOfWorkFactory,
)
from .queries.get_allowlist import GetCapabilityAllowlist
from .queries.get_runner_history import GetRunnerHistory
from .queries.list_runners import GetRunner, ListRunners
from .results import (
    AllowlistView,
    Assignment,
    CreatedRunner,
    HeartbeatResult,
    JobRequestResult,
    NotAssignedKind,
    NotAssignedReason,
    RunnerView,
    SweepResult,
)

__all__ = [
    "AllowlistView",
    "AlreadyInMaintenance",
    "Assignment",
    "AuthenticateRunner",
    "CapabilityAllowlistRepository",
    "ClearFault",
    "ClearMaintenance",
    "CreateRunner",
    "CreatedRunner",
    "DeleteRunner",
    "DuplicateRunnerName",
    "GetCapabilityAllowlist",
    "GetRunner",
    "GetRunnerHistory",
    "Heartbeat",
    "HeartbeatResult",
    "InvalidDeclaration",
    "InvalidLeaseTransition",
    "InvalidRequirement",
    "InvalidTimingPolicy",
    "IssuedToken",
    "JobRequestResult",
    "LeaseExpired",
    "LeaseRepository",
    "LeaseStatus",
    "ListRunners",
    "NotAssignedKind",
    "NotAssignedReason",
    "NotInMaintenance",
    "RegisterRunner",
    "ReissueToken",
    "ReplaceCapabilityAllowlist",
    "ReportFault",
    "ReportRecovered",
    "RequestJob",
    "RevokeToken",
    "RunnerAuthenticationFailed",
    "RunnerCatalog",
    "RunnerDeleted",
    "RunnerDependencies",
    "RunnerEligibilityService",
    "RunnerHasUnfinishedJob",
    "RunnerIdentityMismatch",
    "RunnerNotFound",
    "RunnerNotRegistered",
    "RunnerRepository",
    "RunnerState",
    "RunnerTimingPolicy",
    "RunnerTokenRepository",
    "RunnerUnitOfWork",
    "RunnerUnitOfWorkFactory",
    "RunnerView",
    "SetMaintenance",
    "SweepResult",
    "SweepRunners",
    "ValueKind",
]
