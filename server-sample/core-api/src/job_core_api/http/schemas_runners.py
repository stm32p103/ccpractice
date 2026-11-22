"""ランナー・許可リストのモデル(contracts/http-api.md §2.3)。

トークンの値は、発行の応答の型(CreatedRunnerOut、IssuedTokenOut)だけに置く(FR-026、T-A1)。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from job_core.runner.application import AllowlistView, CreatedRunner, RunnerView
from job_core.runner.domain.runner import RunnerState
from job_core.runner.domain.token import IssuedToken
from job_core.runner.domain.values import ValueKind

from .schemas_jobs import ApiModel


class IssuedTokenOut(ApiModel):
    token_id: str
    token: str = Field(description="トークンの値。この応答だけで返り、以後は取得できない")

    @classmethod
    def of(cls, issued: IssuedToken) -> IssuedTokenOut:
        return cls(token_id=issued.token_id, token=issued.value)


class CreateRunnerRequest(ApiModel):
    name: str


class CreatedRunnerOut(ApiModel):
    runner_id: str
    token: IssuedTokenOut

    @classmethod
    def of(cls, created: CreatedRunner) -> CreatedRunnerOut:
        return cls(runner_id=created.runner_id, token=IssuedTokenOut.of(created.token))


class RunnerOut(ApiModel):
    runner_id: str
    name: str
    state: RunnerState
    capabilities: dict[str, str | list[str]]
    fault_description: str | None
    maintenance_reason: str | None
    running_job_id: str | None
    last_seen_at: datetime | None
    registered_at: datetime | None

    @classmethod
    def of(cls, view: RunnerView) -> RunnerOut:
        return cls(
            runner_id=view.runner_id,
            name=view.name,
            state=view.state,
            capabilities=dict(view.capabilities),
            fault_description=view.fault_description,
            maintenance_reason=view.maintenance_reason,
            running_job_id=view.running_job_id,
            last_seen_at=view.last_seen_at,
            registered_at=view.registered_at,
        )


class MaintenanceRequest(ApiModel):
    reason: str | None = None


class AllowlistOut(ApiModel):
    entries: dict[str, ValueKind]

    @classmethod
    def of(cls, view: AllowlistView) -> AllowlistOut:
        return cls(entries={str(key): kind for key, kind in view.entries.items()})


class ReplaceAllowlistRequest(ApiModel):
    entries: dict[str, ValueKind] = Field(description="能力のキー → 値の型(single または set)")
    reason: str | None = None
