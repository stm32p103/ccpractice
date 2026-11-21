"""ListRunners / GetRunner — ランナーの一覧と詳細(FR-027)。

job.general を要する(001 の閲覧と同じ)。トークンの値・ハッシュ・token_id、削除済みのランナーは含めない。
"""

from __future__ import annotations

from job_core.access.principal import Principal

from ..authorization import authorize_view
from ..commands._common import load_runner, view_of
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import RunnerView
from ..uow_support import run_in_runner_uow


class ListRunners:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal) -> tuple[RunnerView, ...]:
        deps = self._deps
        authorize_view(principal)

        def read(uow: RunnerUnitOfWork) -> tuple[RunnerView, ...]:
            now = deps.clock.now()
            return tuple(view_of(uow, deps, runner, now) for runner in uow.runners.list_active())

        return run_in_runner_uow(deps, read)


class GetRunner:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str) -> RunnerView:
        deps = self._deps
        authorize_view(principal)

        def read(uow: RunnerUnitOfWork) -> RunnerView:
            return view_of(uow, deps, load_runner(uow, runner_id), deps.clock.now())

        return run_in_runner_uow(deps, read)
