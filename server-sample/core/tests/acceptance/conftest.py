"""受け入れテストの共通フィクスチャ(Fake の組み立て、権限の組み合わせを持つ主体、ジョブ定義の生成)。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from job_core.access.permission import Permission
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application import AuditOutcome, JobState, Placement, SubmitResult
from job_core.job.domain.job import Job
from job_core.job.domain.queue import Queue
from job_core.shared.ids import JobId
from job_testing.contracts.persistence import assert_queue_consistent
from job_testing.core_fakes import CoreFixture, build_core

P = Permission

SUBMITTER_PERMS = {P.JOB_SUBMIT, P.GENERAL}
SCHEDULER_PERMS = {P.JOB_SUBMIT, P.GENERAL, P.QUEUE_SCHEDULE}


def principal(subject: str, permissions: Iterable[Permission], kind: PrincipalKind = PrincipalKind.HUMAN) -> Principal:
    return Principal.of(subject, permissions, kind)


@dataclass
class Env:
    """1 つのテストの環境。"""

    core: CoreFixture
    alice: Principal  # 一般の提出者
    bob: Principal  # 別の一般の提出者
    scheduler: Principal  # スケジュール変更の権限を持つ利用者
    canceller: Principal  # 取り消しの権限だけを持つ利用者
    aborter: Principal  # 強制中断の権限だけを持つ利用者
    admin: Principal  # 管理の権限だけを持つ利用者
    service: Principal  # 提出代行のサービス
    runner1: Principal  # ランナー R1 の主体(job.execute)
    runner2: Principal  # ランナー R2 の主体(job.execute)
    purger: Principal  # 保持期間による削除の主体
    viewer: Principal  # 閲覧の権限(一般)だけを持つ利用者

    def submit(self, who: Principal | None = None, **overrides: Any) -> SubmitResult:
        values: dict[str, Any] = {
            "job_type": "type-a",
            "requirement": {"os": "x"},
            "payload": {"args": ["--run"]},
            "timeout": timedelta(minutes=30),
        }
        values.update(overrides)
        return self.core.submit(who or self.alice, **values)

    def submit_many(self, count: int, who: Principal | None = None, **overrides: Any) -> list[JobId]:
        return [self.submit(who, **overrides).job_id for _ in range(count)]

    def queue(self) -> Queue:
        with self.core.new_uow() as uow:
            return uow.queue.get()

    def queue_ids(self) -> list[str]:
        return list(self.queue().entries)

    def job(self, job_id: str) -> Job:
        with self.core.new_uow() as uow:
            job = uow.jobs.get(JobId(job_id))
            assert job is not None
            return job

    def assign(self, runner: Principal | None = None, runner_id: str = "R1") -> JobId | None:
        return self.core.assign(runner or self.runner1, runner_id=runner_id).job_id

    def run(self, job_id: str, runner_id: str = "R1") -> None:
        """待機列の先頭にあるものとして job_id を割り当てる(先頭でなければ失敗させる)。"""
        assigned = self.assign(self.runner1 if runner_id == "R1" else self.runner2, runner_id)
        assert assigned == job_id, f"割り当てられたのは {assigned}(期待 {job_id})"

    def finish(self, job_id: str, outcome: JobState = JobState.SUCCEEDED, runner_id: str = "R1") -> None:
        runner = self.runner1 if runner_id == "R1" else self.runner2
        self.core.report_finished(runner, runner_id=runner_id, job_id=job_id, outcome=outcome)

    def denied_records(self) -> list[Any]:
        page = self.core.get_audit_log(self.admin, outcome=AuditOutcome.DENIED, limit=1000)
        # 閲覧そのものの記録は残らない(成功した閲覧は状態を変えない)
        return list(page.items)

    def assert_consistent(self) -> None:
        with self.core.new_uow() as uow:
            assert_queue_consistent(uow)


@pytest.fixture
def env() -> Env:
    core = build_core()
    core.runners.register("R1", {"os": "x"})
    core.runners.register("R2", {"os": "y"})
    return Env(
        core=core,
        alice=principal("alice", SUBMITTER_PERMS),
        bob=principal("bob", SUBMITTER_PERMS),
        scheduler=principal("sched", SCHEDULER_PERMS),
        canceller=principal("canceller", {P.GENERAL, P.CANCEL_QUEUED}),
        aborter=principal("aborter", {P.GENERAL, P.FORCE_ABORT}),
        admin=principal("admin", {P.AUDIT_READ_ALL}),
        service=principal("svc", {P.SUBMIT_ON_BEHALF}, PrincipalKind.SERVICE),
        runner1=principal("runner-R1", {P.JOB_EXECUTE}, PrincipalKind.RUNNER),
        runner2=principal("runner-R2", {P.JOB_EXECUTE}, PrincipalKind.RUNNER),
        purger=principal("purger", {P.RETENTION_PURGE}, PrincipalKind.SYSTEM),
        viewer=principal("viewer", {P.GENERAL}),
    )


__all__ = ["Env", "Placement", "principal"]
