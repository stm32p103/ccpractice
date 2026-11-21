"""楽観的排他の衝突時に、判定からやり直す(research.md R4、contracts/application-api.md「共通の約束」)。

ここでの「やり直し」は同時更新の衝突の再試行であり、業務用語のやり直し(RetryJob)とは別のもの。
"""

from __future__ import annotations

from collections.abc import Callable

from job_core.job.domain.errors import ConcurrencyConflict

from .ports import UnitOfWork, UnitOfWorkFactory


def run_in_unit_of_work[T](
    uow_factory: UnitOfWorkFactory,
    operation: Callable[[UnitOfWork], T],
    *,
    attempts: int = 3,
) -> T:
    """operation を 1 回の UoW で実行してコミットする。衝突したら最新の状態を読み直して最初からやり直す。

    operation は UoW の中で読み込み・判定・変更・記録を行う。例外を送出したら何も確定しない。
    やり直しを使い切ったら ConcurrencyConflict を送出する。
    """
    if attempts < 1:
        raise ValueError("attempts は 1 以上")
    last: ConcurrencyConflict | None = None
    for _ in range(attempts):
        with uow_factory() as uow:
            result = operation(uow)
            try:
                uow.commit()
            except ConcurrencyConflict as conflict:
                last = conflict
                continue
            return result
    raise last if last is not None else ConcurrencyConflict()
