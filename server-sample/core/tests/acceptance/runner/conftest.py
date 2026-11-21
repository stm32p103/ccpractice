"""ランナー管理の受け入れテストの共通フィクスチャ(Fake をつないだ RunnerDependencies、手動で進める時計、主体の作り方)。

能力のキーは記号(k1、k2、set1)を使う(用途固有の語を使わない)。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from job_core.access.permission import Permission
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application import AuditOutcome, JobState, SubmitResult
from job_core.job.domain.definition import JobDefinition, Submitter
from job_core.job.domain.job import Job
from job_core.runner.application import CreatedRunner, JobRequestResult, RunnerTimingPolicy
from job_core.shared.ids import JobId
from job_testing.core_fakes import CoreFixture, build_core

P = Permission

DEFAULT_ALLOWLIST = {"k1": "single", "k2": "single", "set1": "set"}


def eq(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "op": "eq", "value": value}


def contains(key: str, *values: str) -> dict[str, Any]:
    return {"key": key, "op": "contains", "values": list(values)}


def requirement(*conditions: dict[str, Any]) -> dict[str, Any]:
    return {"all": list(conditions)}


@dataclass
class RunnerHandle:
    """作成・認証済みのランナー。principal は AuthenticateRunner の戻り値。"""

    runner_id: str
    token: str
    principal: Principal


@dataclass
class RunnerEnv:
    core: CoreFixture
    admin: Principal  # ランナー管理 + 閲覧
    auditor: Principal  # 監査ログ全体の閲覧(001 の「管理」)
    sweeper: Principal  # 定期処理
    viewer: Principal  # 閲覧だけ
    alice: Principal  # ジョブの提出者
    nobody: Principal  # 権限なし

    # ------------------------------------------------------------------ ランナー

    def create(self, name: str = "r-a") -> CreatedRunner:
        return self.core.create_runner(self.admin, name=name)

    def runner(
        self,
        name: str = "r-a",
        capabilities: dict[str, Any] | None = None,
        *,
        register: bool = True,
    ) -> RunnerHandle:
        """作成 → 認証 → (既定で)登録まで行う。"""
        created = self.create(name)
        principal = self.core.authenticate_runner(created.token.value)
        handle = RunnerHandle(created.runner_id, created.token.value, principal)
        if register:
            self.core.register_runner(principal, runner_id=created.runner_id, capabilities=capabilities or {})
        return handle

    def heartbeat(self, handle: RunnerHandle) -> Any:
        return self.core.heartbeat(handle.principal, runner_id=handle.runner_id)

    def request(self, handle: RunnerHandle) -> JobRequestResult:
        return self.core.request_job(handle.principal, runner_id=handle.runner_id)

    def state(self, runner_id: str) -> str:
        return self.core.get_runner(self.viewer, runner_id=runner_id).state.value

    # ------------------------------------------------------------------ ジョブ

    def submit(self, req: dict[str, Any] | None = None, who: Principal | None = None, **overrides: Any) -> SubmitResult:
        values: dict[str, Any] = {
            "job_type": "type-a",
            "requirement": req if req is not None else requirement(),
            "payload": {"args": ["--run"]},
            "timeout": timedelta(minutes=30),
        }
        values.update(overrides)
        return self.core.submit(who or self.alice, **values)

    def enqueue_raw(self, req: dict[str, Any], *, source: str | None = None) -> str:
        """提出の判定(要件を満たしうるランナーの有無)を通さずに、待機列の末尾へ直接並べる(判定と割り当ての一致の検査用)。"""
        definition = JobDefinition.create(
            job_type="type-a", requirement=req, payload={"p": 1}, timeout=timedelta(minutes=30), source=source
        )
        job = Job.submit(
            job_id=JobId(self.core.ids.new_id()),
            definition=definition,
            submitter=Submitter(owner=self.alice.subject_id, submitted_by=self.alice.subject_id),
            at=self.core.clock.now(),
        )
        with self.core.new_uow() as uow:
            uow.jobs.add(job)
            queue = uow.queue.get()
            queue.append(job.job_id)
            uow.queue.save(queue)
            uow.commit()
        return job.job_id

    def job(self, job_id: str) -> Job:
        with self.core.new_uow() as uow:
            job = uow.jobs.get(JobId(job_id))
            assert job is not None
            return job

    def finish(self, handle: RunnerHandle, job_id: str, outcome: JobState = JobState.SUCCEEDED) -> None:
        self.core.report_finished(handle.principal, runner_id=handle.runner_id, job_id=job_id, outcome=outcome)

    def queue_ids(self) -> list[str]:
        with self.core.new_uow() as uow:
            return list(uow.queue.get().entries)

    # ------------------------------------------------------------------ 時刻・監査

    def advance(self, seconds: float) -> None:
        self.core.clock.advance(timedelta(seconds=seconds))

    def denied(self) -> list[Any]:
        return list(self.core.get_audit_log(self.auditor, outcome=AuditOutcome.DENIED, limit=1000).items)

    def audit(self, **filters: Any) -> list[Any]:
        return list(self.core.get_audit_log(self.auditor, limit=1000, **filters).items)


def make_env(timing: RunnerTimingPolicy | None = None, allowlist: dict[str, str] | None = None) -> RunnerEnv:
    core = build_core(use_runner_management=True, timing=timing)
    env = RunnerEnv(
        core=core,
        admin=Principal.of("admin", {P.RUNNER_MANAGE, P.GENERAL}),
        auditor=Principal.of("auditor", {P.AUDIT_READ_ALL}),
        sweeper=Principal.of("sweeper", {P.RUNNER_SWEEP}, PrincipalKind.SYSTEM),
        viewer=Principal.of("viewer", {P.GENERAL}),
        alice=Principal.of("alice", {P.JOB_SUBMIT, P.GENERAL}),
        nobody=Principal.of("nobody", set()),
    )
    core.replace_allowlist(env.admin, entries=DEFAULT_ALLOWLIST if allowlist is None else allowlist)
    return env


@pytest.fixture
def env() -> RunnerEnv:
    return make_env()


def principals_with(permissions: Iterable[Permission]) -> Principal:
    return Principal.of("someone", permissions)
