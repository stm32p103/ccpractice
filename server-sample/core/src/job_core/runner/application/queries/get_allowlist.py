"""GetCapabilityAllowlist — 能力のキーの許可リストの閲覧(job.general)。"""

from __future__ import annotations

from job_core.access.principal import Principal

from ..authorization import authorize_view
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import AllowlistView
from ..uow_support import run_in_runner_uow


class GetCapabilityAllowlist:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal) -> AllowlistView:
        authorize_view(principal)

        def read(uow: RunnerUnitOfWork) -> AllowlistView:
            return AllowlistView({str(k): v for k, v in uow.allowlist.get().entries.items()})

        return run_in_runner_uow(self._deps, read)
