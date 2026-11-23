"""ユースケースの出力の型(contracts/application-api.md)。

トークンの値・ハッシュ・token_id は、発行の戻り値(CreatedRunner、IssuedToken)以外の出力に含めない(FR-027、SC-008)。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from job_core.job.application.queries.job_views import DefinitionView
from job_core.runner.domain.runner import Runner, RunnerState
from job_core.runner.domain.token import IssuedToken
from job_core.runner.domain.values import RunnerTimingPolicy, ValueKind
from job_core.shared.ids import JobId, RunnerId


@dataclass(frozen=True)
class CreatedRunner:
    runner_id: RunnerId
    token: IssuedToken


@dataclass(frozen=True)
class HeartbeatResult:
    """登録・生存通知・異常と回復の申告への応答。lease_expires_at は、有効なリースがあるときだけ。"""

    state: RunnerState
    lease_expires_at: datetime | None
    heartbeat_interval: timedelta
    abort_requested: bool = False
    """004: このランナーに割り当て中のジョブに、中断の要求がある(強制中断の指示。真偽だけ)。"""


class NotAssignedKind(StrEnum):
    NOT_ONLINE = "not_online"
    RUNNER_BUSY = "runner_busy"
    NO_MATCHING_JOB = "no_matching_job"


@dataclass(frozen=True)
class NotAssignedReason:
    """「割り当てなし」の理由。NOT_ONLINE は state、RUNNER_BUSY は job_id を持つ。"""

    kind: NotAssignedKind
    state: RunnerState | None = None
    job_id: JobId | None = None


@dataclass(frozen=True)
class Assignment:
    job_id: JobId
    definition: DefinitionView
    lease_id: str
    lease_expires_at: datetime


@dataclass(frozen=True)
class JobRequestResult:
    assignment: Assignment | None
    not_assigned_reason: NotAssignedReason | None
    heartbeat_interval: timedelta


@dataclass(frozen=True)
class SweepResult:
    runners_marked_offline: int
    leases_expired: int
    leases_ended: int


@dataclass(frozen=True)
class RunnerView:
    runner_id: RunnerId
    name: str
    state: RunnerState
    capabilities: Mapping[str, str | list[str]]
    fault_description: str | None
    maintenance_reason: str | None
    running_job_id: JobId | None
    last_seen_at: datetime | None
    registered_at: datetime | None


@dataclass(frozen=True)
class AllowlistView:
    entries: Mapping[str, ValueKind]


def runner_view(
    runner: Runner, *, now: datetime, policy: RunnerTimingPolicy, running_job_id: JobId | None
) -> RunnerView:
    return RunnerView(
        runner_id=runner.runner_id,
        name=runner.name.value,
        state=runner.state_at(now, policy),
        capabilities=runner.capabilities.to_json(),
        fault_description=runner.fault.description.value if runner.fault else None,
        maintenance_reason=(
            runner.maintenance.reason.value if runner.maintenance and runner.maintenance.reason else None
        ),
        running_job_id=running_job_id,
        last_seen_at=runner.last_seen_at,
        registered_at=runner.registered_at,
    )
