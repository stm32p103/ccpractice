"""quickstart.md §4 のシナリオ 1〜11 を通しで実行する(build_core() を使用)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application import (
    AuditOutcome,
    JobState,
    NoEligibleRunner,
    PermissionDenied,
    Placement,
    RunnerMismatch,
)
from job_testing.core_fakes import build_core


def test_quickstart_walkthrough() -> None:
    core = build_core()
    core.runners.register("R1", {"os": "x"})
    core.runners.register("R2", {"os": "x"})
    alice = Principal.of("alice", [P.JOB_SUBMIT, P.GENERAL])
    bob = Principal.of("bob", [P.JOB_SUBMIT, P.GENERAL])
    scheduler = Principal.of("sched", [P.JOB_SUBMIT, P.GENERAL, P.QUEUE_SCHEDULE])
    aborter = Principal.of("aborter", [P.GENERAL, P.FORCE_ABORT])
    admin = Principal.of("admin", [P.AUDIT_READ_ALL])
    r1 = Principal.of("runner-R1", [P.JOB_EXECUTE], PrincipalKind.RUNNER)
    r2 = Principal.of("runner-R2", [P.JOB_EXECUTE], PrincipalKind.RUNNER)

    def submit(who: Principal, **kw: object) -> str:
        values: dict[str, object] = {
            "job_type": "t",
            "requirement": {"os": "x"},
            "payload": {},
            "timeout": timedelta(minutes=5),
        }
        values.update(kw)
        return core.submit(who, **values).job_id  # type: ignore[arg-type]

    def queued() -> list[str]:
        return [s.job_id for s in core.list_jobs(alice).queued]

    # 1. 並んだ順に実行される
    first, second = submit(alice), submit(alice)
    assert core.assign(r1, runner_id="R1").job_id == first
    core.report_finished(r1, runner_id="R1", job_id=first, outcome="failed")

    # 2. 要件を満たすランナーがない
    with pytest.raises(NoEligibleRunner):
        submit(alice, requirement={"os": "none"})

    # 3. 先頭の前に追加(割り込み)
    a, b, c = second, submit(bob), submit(bob)
    x = submit(scheduler, placement=Placement.before(a))
    assert queued() == [x, a, b, c]

    # 4. 移動
    core.reschedule(scheduler, job_id=c, placement=Placement.before(x))
    assert queued() == [c, x, a, b]
    core.reschedule(scheduler, job_id=c, placement=Placement.after(b))
    assert queued() == [x, a, b, c]

    # 5. 権限のない位置指定
    with pytest.raises(PermissionDenied):
        submit(alice, placement=Placement.before(a))
    assert len(core.get_audit_log(admin, outcome=AuditOutcome.DENIED).items) == 1

    # 6. 強制中断
    assert core.assign(r1, runner_id="R1").job_id == x
    assert core.cancel(aborter, job_id=x, reason="保守").abort_pending
    assert core.confirm_stopped(r1, runner_id="R1", job_id=x).state is JobState.CANCELLED

    # 7. やり直し
    retried = core.retry(bob, job_id=first).job_id
    assert queued()[-1] == retried
    assert core.get_job(alice, job_id=first).retries == (retried,)
    detail = core.get_job(alice, job_id=retried)
    assert detail.summary.owner == "bob" and detail.retry_of is not None and detail.retry_of.job_id == first

    # 8. 操作の経緯
    history = core.get_job_history(alice, job_id=c)
    moves = [r for r in history if r.operation.value == "reschedule"]
    assert [m.actor for m in moves] == ["sched", "sched"]
    assert all(r.outcome is AuditOutcome.SUCCEEDED for r in history)

    # 9. 取りこぼしのない完了イベント
    with core.new_uow() as uow:
        once = [e.event.event_id for e in uow.outbox.fetch_pending(10)]
        twice = [e.event.event_id for e in uow.outbox.fetch_pending(10)]
    assert once == twice and len(once) == 2  # first(失敗)と x(中断)

    # 10. 割り当て先でないランナーからの報告
    assert core.assign(r1, runner_id="R1").job_id == a
    with pytest.raises(RunnerMismatch):
        core.report_finished(r2, runner_id="R2", job_id=a, outcome="succeeded")
    assert core.get_job(alice, job_id=a).summary.state is JobState.RUNNING
    assert len(core.get_audit_log(admin, outcome=AuditOutcome.DENIED).items) == 2

    # 11. 権限での判定(主体の種類が RUNNER でも、job.execute がなければ拒否)
    pretender = Principal.of("pretender", [P.GENERAL], PrincipalKind.RUNNER)
    with pytest.raises(PermissionDenied):
        core.assign(pretender, runner_id="R2")
