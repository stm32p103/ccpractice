"""同名の同時の作成の競合(data-model.md §8 の不変条件 4)。一方だけが成立する。"""

from __future__ import annotations

import threading

import pytest

from job_core.runner.application import DuplicateRunnerName

from .conftest import RunnerEnv


def test_interleaved_creation_of_same_name_lets_only_one_succeed(env: RunnerEnv) -> None:
    results: list[object] = []

    def other_create() -> None:
        results.append(env.core.create_runner(env.admin, name="same"))

    # 最初の作成の確定の直前に、同じ名前の作成が割り込んで確定する
    env.core.store.inject_before_next_commit(other_create)
    with pytest.raises(DuplicateRunnerName):  # 割り込んだ方が先に確定し、元の作成はやり直して重複として拒否される
        env.core.create_runner(env.admin, name="same")
    assert len(results) == 1
    assert [v.name for v in env.core.list_runners(env.viewer)] == ["same"]


def test_parallel_creation_of_same_name_creates_exactly_one(env: RunnerEnv) -> None:
    successes: list[object] = []
    failures: list[Exception] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        try:
            successes.append(env.core.create_runner(env.admin, name="same"))
        except Exception as error:
            failures.append(error)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(successes) == 1
    assert len(failures) == 3
    assert all(isinstance(f, DuplicateRunnerName) or type(f).__name__ == "ConcurrencyConflict" for f in failures)
    assert [v.name for v in env.core.list_runners(env.viewer)] == ["same"]


def test_names_are_reusable_after_deletion(env: RunnerEnv) -> None:
    first = env.create("same")
    env.core.delete_runner(env.admin, runner_id=first.runner_id)
    second = env.create("same")
    assert second.runner_id != first.runner_id
    with pytest.raises(DuplicateRunnerName):
        env.create("same")
