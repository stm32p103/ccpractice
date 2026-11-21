"""同時の要求(spec US3-5、SC-002、SC-006。data-model.md §8 の不変条件 1・6)。"""

from __future__ import annotations

import threading

from job_core.runner.application import JobRequestResult, NotAssignedKind, RunnerState

from .conftest import RunnerEnv


def assert_lease_invariants(env: RunnerEnv) -> None:
    with env.core.new_uow() as uow:
        leases = uow.leases.list_active()
        assert len({lease.job_id for lease in leases}) == len(leases)  # 1 件のジョブに ACTIVE は高々 1 つ
        assert len({lease.runner_id for lease in leases}) == len(leases)  # 1 台のランナーにも


def test_us3_5_interleaved_requests_assign_the_job_to_one_runner_only(env: RunnerEnv) -> None:
    a = env.runner("r-a", {})
    b = env.runner("r-b", {})
    job = env.submit().job_id
    results: dict[str, JobRequestResult] = {}

    # a の確定の直前に、b の要求が割り込んで確定する
    env.core.store.inject_before_next_commit(lambda: results.setdefault("b", env.request(b)))
    results["a"] = env.request(a)

    assert results["b"].assignment is not None
    assert results["b"].assignment.job_id == job
    assert results["a"].assignment is None  # a はやり直して、もう割り当てるジョブがない
    assert results["a"].not_assigned_reason is not None
    assert results["a"].not_assigned_reason.kind is NotAssignedKind.NO_MATCHING_JOB
    assert env.job(job).assigned_runner_id == b.runner_id
    assert_lease_invariants(env)


def test_parallel_requests_for_one_job_assign_exactly_once(env: RunnerEnv) -> None:
    handles = [env.runner(f"r-{i}", {}) for i in range(6)]
    job = env.submit().job_id
    results: list[JobRequestResult] = []
    barrier = threading.Barrier(len(handles))

    def worker(index: int) -> None:
        barrier.wait()
        results.append(env.request(handles[index]))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(handles))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assigned = [r for r in results if r.assignment is not None]
    assert len(results) == len(handles)
    assert len(assigned) == 1
    assert assigned[0].assignment is not None and assigned[0].assignment.job_id == job
    assert_lease_invariants(env)


def test_maintenance_set_during_request_wins_over_assignment(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    env.core.store.inject_before_next_commit(
        lambda: env.core.set_maintenance(env.admin, runner_id=runner.runner_id, reason="保守")
    )
    result = env.request(runner)
    # 割り当てはやり直され、状態を見て「割り当てなし」になる(SC-006)
    assert result.assignment is None
    assert result.not_assigned_reason is not None
    assert result.not_assigned_reason.kind is NotAssignedKind.NOT_ONLINE
    assert result.not_assigned_reason.state is RunnerState.MAINTENANCE
    assert env.queue_ids() == [job]
    assert_lease_invariants(env)


def test_fault_reported_during_request_wins_over_assignment(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    job = env.submit().job_id
    env.core.store.inject_before_next_commit(
        lambda: env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    )
    result = env.request(runner)
    assert result.assignment is None
    assert result.not_assigned_reason is not None
    assert result.not_assigned_reason.state is RunnerState.FAULT
    assert env.queue_ids() == [job]


def test_no_lease_exists_for_a_runner_that_was_not_online_when_assigned(env: RunnerEnv) -> None:
    online = env.runner("r-a", {})
    stopped = env.runner("r-b", {})
    env.core.set_maintenance(env.admin, runner_id=stopped.runner_id)
    for _ in range(3):
        env.submit()
    env.request(stopped)
    env.request(online)
    with env.core.new_uow() as uow:
        assert [lease.runner_id for lease in uow.leases.list_active()] == [online.runner_id]
