"""同時実行の試験(PostgreSQL。SC-002、SC-006。001・002 の同時実行の受け入れテストと同じ観点)。"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from sqlalchemy import Engine

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal
from job_core.job.application import AssignNextJob, CancelJob, RescheduleJob, SubmitJob
from job_core.job.domain.states import JobState
from job_core.job.domain.values import Placement
from job_core.runner.application import (
    CreateRunner,
    RegisterRunner,
    ReplaceCapabilityAllowlist,
    RequestJob,
    RunnerDependencies,
    RunnerEligibilityService,
    RunnerTimingPolicy,
)
from job_core_persistence import SqlRunnerCatalog, sql_uow_factory
from job_testing.core_fakes import FakeClock, FakeSecretGenerator, SequentialIdGenerator

pytestmark = pytest.mark.postgres

ADMIN = Principal.of("admin", [P.RUNNER_MANAGE, P.GENERAL])
USER = Principal.of("alice", [P.JOB_SUBMIT, P.GENERAL, P.QUEUE_SCHEDULE, P.CANCEL_QUEUED])
REQ = {"all": [{"key": "k1", "op": "eq", "value": "v"}]}


def build(engine: Engine) -> RunnerDependencies:
    catalog = SqlRunnerCatalog(engine)
    return RunnerDependencies(
        uow_factory=sql_uow_factory(engine),
        eligibility=RunnerEligibilityService(catalog),
        clock=FakeClock(),
        ids=SequentialIdGenerator(),
        max_conflict_retries=8,
        catalog=catalog,
        secrets=FakeSecretGenerator(),
        timing=RunnerTimingPolicy(),
    )


def submit(deps: RunnerDependencies, n: int) -> str:
    result = SubmitJob(deps)(USER, job_type="t", requirement=REQ, payload={"n": n}, timeout=timedelta(minutes=1))
    return str(result.job_id)


def runner_ids(deps: RunnerDependencies, count: int) -> list[str]:
    ReplaceCapabilityAllowlist(deps)(ADMIN, entries={"k1": "single"})
    ids = []
    for i in range(count):
        created = CreateRunner(deps)(ADMIN, name=f"r{i}")
        principal = Principal.of(created.runner_id, [P.RUNNER_REPORT, P.JOB_EXECUTE])
        RegisterRunner(deps)(principal, runner_id=created.runner_id, capabilities={"k1": "v"})
        ids.append(str(created.runner_id))
    return ids


def race(actions: list) -> list:  # type: ignore[type-arg]
    barrier = threading.Barrier(len(actions))
    results: list = [None] * len(actions)  # type: ignore[type-arg]

    def run(index: int) -> None:
        barrier.wait()
        try:
            results[index] = actions[index]()
        except Exception as error:
            results[index] = error

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(actions))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def test_one_job_is_never_assigned_to_two_runners(engine: Engine) -> None:
    deps = build(engine)
    runners = runner_ids(deps, 4)
    for round_ in range(5):
        submit(deps, round_)
        results = race(
            [
                (lambda rid=rid: RequestJob(deps)(Principal.of(rid, [P.RUNNER_REPORT, P.JOB_EXECUTE]), runner_id=rid))
                for rid in runners
            ]
        )
        errors = [r for r in results if isinstance(r, Exception)]
        assigned = [r for r in results if not isinstance(r, Exception) and r.assignment is not None]
        assert errors == [], errors
        assert len(assigned) == 1, f"round {round_}: {len(assigned)} 台に割り当てられた"
        # 割り当てたランナーを、次の回のために解放する(終了の報告)
        winner = assigned[0].assignment
        from job_core.job.application import ReportFinished

        for rid in runners:
            try:
                ReportFinished(deps)(
                    Principal.of(rid, [P.RUNNER_REPORT, P.JOB_EXECUTE]),
                    runner_id=rid,
                    job_id=winner.job_id,
                    outcome="succeeded",
                )
                break
            except Exception:
                continue


def test_reschedule_and_cancel_race_leaves_the_queue_consistent(engine: Engine) -> None:
    deps = build(engine)
    runner_ids(deps, 1)
    for n in range(5):
        a, b, c = submit(deps, n * 10), submit(deps, n * 10 + 1), submit(deps, n * 10 + 2)
        results = race(
            [
                lambda a=a, c=c: RescheduleJob(deps)(USER, job_id=c, placement=Placement.before(a)),
                lambda b=b: CancelJob(deps)(USER, job_id=b),
                lambda a=a: CancelJob(deps)(USER, job_id=a),
            ]
        )
        unexpected = [
            r
            for r in results
            if isinstance(r, Exception) and type(r).__name__ not in {"TargetNotQueued", "AnchorNotQueued"}
        ]
        assert unexpected == [], unexpected
        with deps.uow_factory() as uow:
            queued = {j.job_id for j in uow.jobs.list_by_states([JobState.QUEUED], None, None).items}
            entries = list(uow.queue.get().entries)
        assert set(entries) == queued and len(entries) == len(set(entries))
        for job_id in entries:  # 次の回のために空にする
            CancelJob(deps)(USER, job_id=job_id)


_UNUSED = AssignNextJob
