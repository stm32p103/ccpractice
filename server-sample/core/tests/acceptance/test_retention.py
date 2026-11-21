"""保持期間による削除(FR-031、FR-032)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.job.application import (
    AuditOperation,
    JobNotFound,
    JobState,
    PermissionDenied,
    RetentionPolicy,
    ValidationFailed,
)

from .conftest import Env


def finished(env: Env, state: JobState = JobState.SUCCEEDED) -> str:
    job_id = env.submit().job_id
    env.run(job_id)
    env.finish(job_id, state)
    return job_id


def test_defaults_are_one_and_three_years() -> None:
    policy = RetentionPolicy()
    assert policy.job_retention == timedelta(days=365)
    assert policy.audit_retention == timedelta(days=1095)


def test_audit_retention_cannot_be_shorter_than_job_retention() -> None:
    with pytest.raises(ValidationFailed):
        RetentionPolicy(job_retention=timedelta(days=100), audit_retention=timedelta(days=99))
    with pytest.raises(ValidationFailed):
        RetentionPolicy(job_retention=timedelta(0))
    assert RetentionPolicy(job_retention=timedelta(days=10), audit_retention=timedelta(days=10))


def test_only_expired_finished_jobs_are_deleted(env: Env) -> None:
    old = finished(env)
    running = env.submit(requirement={"os": "y"}).job_id
    env.run(running, "R2")  # 古いまま実行中のジョブ
    env.core.runners.register("R3", {"os": "z"})
    queued = env.submit(env.bob, requirement={"os": "z"}).job_id  # 古いまま待機中のジョブ(R3 には割り当てない)
    env.core.clock.advance(timedelta(days=366))
    recent = finished(env)
    result = env.core.purge(env.purger)
    assert result.jobs_deleted == 1
    with env.core.new_uow() as uow:
        assert not uow.jobs.exists(old)
        for kept in (running, queued, recent):
            assert uow.jobs.exists(kept), kept


def test_expired_audit_records_are_deleted_and_purge_is_audited(env: Env) -> None:
    finished(env)
    env.core.clock.advance(timedelta(days=1096))
    result = env.core.purge(env.purger)
    assert result.jobs_deleted == 1
    assert result.audit_records_deleted >= 3  # 提出・割り当て・完了
    log = env.core.get_audit_log(env.admin, limit=1000).items
    assert [r.operation for r in log] == [AuditOperation.PURGE]
    assert log[0].after["jobs_deleted"] == 1


def test_history_remains_after_job_is_deleted_and_retry_link_says_deleted(env: Env) -> None:
    original = finished(env, JobState.FAILED)
    retried = env.core.retry(env.alice, job_id=original).job_id
    env.core.clock.advance(timedelta(days=400))
    env.core.purge(env.purger)
    ref = env.core.get_job(env.viewer, job_id=retried).retry_of
    assert ref is not None and (ref.job_id, ref.exists) == (original, False)
    with pytest.raises(JobNotFound):
        env.core.retry(env.alice, job_id=original)
    with pytest.raises(JobNotFound):
        env.core.get_job(env.viewer, job_id=original)
    history = env.core.get_job_history(env.viewer, job_id=original)
    assert [r.operation for r in history] == [AuditOperation.SUBMIT, AuditOperation.ASSIGN, AuditOperation.COMPLETE]


def test_purge_requires_permission(env: Env) -> None:
    with pytest.raises(PermissionDenied):
        env.core.purge(env.alice)
    assert [r.operation for r in env.denied_records()] == [AuditOperation.PURGE]
