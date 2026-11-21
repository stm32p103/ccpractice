"""runner のユースケース共通の、Unit of Work の実行(001 の retry_policy を RunnerUnitOfWork として使う)。"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from job_core.job.application.ports import UnitOfWork
from job_core.job.application.retry_policy import run_in_unit_of_work

from .ports import RunnerDependencies, RunnerUnitOfWork


def run_in_runner_uow[T](deps: RunnerDependencies, operation: Callable[[RunnerUnitOfWork], T]) -> T:
    """operation を 1 回の UoW で実行してコミットする。衝突したら、最新の状態を読み直して最初からやり直す。"""

    def adapter(uow: UnitOfWork) -> T:
        return operation(cast(RunnerUnitOfWork, uow))

    return run_in_unit_of_work(deps.uow_factory, adapter, attempts=deps.max_conflict_retries)
