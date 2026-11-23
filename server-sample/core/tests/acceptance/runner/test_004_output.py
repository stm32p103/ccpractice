"""004: ジョブの終了の報告の拡張、ログの追加と参照、成果物の参照(T011、T029)。

001・002 の既存の呼び出し(ReportFinished の拡張前の引数)が変わらず動くことは、既存の受け入れテストが担保する。
"""

from __future__ import annotations

from typing import Any

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal
from job_core.job.application import AuditOutcome, JobState
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import (
    JobNotFound,
    LogQuotaExceeded,
    LogSeqConflict,
    PermissionDenied,
    RunnerMismatch,
    TargetNotRunning,
    ValidationFailed,
)
from job_core.job.domain.output import ArtifactKind, JobArtifactRef, ResultCounters

from .conftest import RunnerEnv, RunnerHandle

SHA = "b" * 64


def reader() -> Principal:
    return Principal.of("reader", {P.GENERAL, P.JOB_READ_OUTPUT})


def running(env: RunnerEnv, name: str = "r-a") -> tuple[RunnerHandle, str]:
    runner = env.runner(name, {})
    job_id = env.submit().job_id
    assert env.request(runner).assignment is not None
    return runner, job_id


def append(env: RunnerEnv, runner: RunnerHandle, job_id: str, seq: int, text: str = "t", stream: str = "stdout") -> Any:
    return env.core.append_log(
        runner.principal, runner_id=runner.runner_id, job_id=job_id, seq=seq, stream=stream, text=text
    )


def ref(name: str = "a.txt") -> JobArtifactRef:
    return JobArtifactRef(name, ArtifactKind.UNC, f"\\\\host\\share\\j\\{name}", 3, SHA)


# ---------------------------------------------------------------- 終了の報告の拡張


def test_finish_report_keeps_detail_and_audits_counts_only(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    env.core.report_finished(
        runner.principal,
        runner_id=runner.runner_id,
        job_id=job_id,
        outcome=JobState.FAILED,
        result_summary="短い要約",
        exit_code=3,
        failure_reason="tool_failed",
        artifacts=[ref()],
        counters=ResultCounters(path_rejections=1, masked_lines=2, log_truncated=True),
    )
    job = env.job(job_id)
    assert job.result_detail is not None
    assert job.result_detail.exit_code == 3
    assert job.result_detail.failure_reason == "tool_failed"
    assert job.result_detail.counters.masked_lines == 2
    reports = [r for r in env.audit() if r.operation is AuditOperation.COMPLETE]
    assert len(reports) == 1
    after = reports[0].after
    assert after["failure_reason"] == "tool_failed"
    assert after["counters"] == {"path_rejections": 1, "masked_lines": 2, "log_truncated": True}
    assert after["artifact_count"] == 1
    assert "UNC" not in repr(after) and "host" not in repr(after)  # 参照を監査に載せない
    assert env.core.outputs.list_artifacts(job_id) == [ref()]  # type: ignore[arg-type]


def test_finish_report_without_extension_is_backward_compatible(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    env.finish(runner, job_id)
    job = env.job(job_id)
    assert job.state is JobState.SUCCEEDED
    assert job.result_detail is not None and job.result_detail.failure_reason is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"result_summary": "x" * 201},
        {"failure_reason": "not-in-vocabulary", "outcome": JobState.FAILED},
        {"failure_reason": "tool_failed"},  # 成功では指定できない
        {"artifacts": [ref()] * 101},
    ],
)
def test_finish_report_rejects_invalid_extension(env: RunnerEnv, kwargs: dict[str, Any]) -> None:
    runner, job_id = running(env)
    kwargs = {"outcome": JobState.SUCCEEDED, **kwargs}
    with pytest.raises(ValidationFailed):
        env.core.report_finished(runner.principal, runner_id=runner.runner_id, job_id=job_id, **kwargs)
    assert env.job(job_id).state is JobState.RUNNING


# ---------------------------------------------------------------- ログの追加


def test_append_is_idempotent_and_conflicts_are_rejected(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    assert not append(env, runner, job_id, 0, "a").duplicate
    assert append(env, runner, job_id, 0, "a").duplicate
    with pytest.raises(LogSeqConflict):
        append(env, runner, job_id, 0, "b")


def test_append_is_limited_to_assigned_runner(env: RunnerEnv) -> None:
    _, job_id = running(env)
    other = env.runner("r-b", {})
    with pytest.raises(RunnerMismatch):
        append(env, other, job_id, 0)
    denied = env.denied()
    assert any(d.denial_code == "runner_mismatch" for d in denied)
    assert env.core.read_log(reader(), job_id=job_id).chunks == ()


def test_append_after_finish_is_rejected(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    env.finish(runner, job_id)
    with pytest.raises(TargetNotRunning):
        append(env, runner, job_id, 0)


def test_append_requires_execute_permission(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    with pytest.raises(PermissionDenied):
        env.core.append_log(env.alice, runner_id=runner.runner_id, job_id=job_id, seq=0, stream="stdout", text="x")
    assert any(d.denial_code == "permission_denied" for d in env.denied())


def test_append_quota_is_enforced(env: RunnerEnv) -> None:
    object.__setattr__(env.core.deps, "log_quota_chars", 5)
    runner, job_id = running(env)
    append(env, runner, job_id, 0, "abcde")
    with pytest.raises(LogQuotaExceeded):
        append(env, runner, job_id, 1, "f")


def test_append_unknown_job_and_bad_stream(env: RunnerEnv) -> None:
    runner, _ = running(env)
    with pytest.raises(JobNotFound):
        append(env, runner, "nope", 0)
    with pytest.raises(ValidationFailed):
        append(env, runner, "nope", 0, stream="other")


# ---------------------------------------------------------------- 参照


def test_read_log_requires_permission_and_is_audited(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    append(env, runner, job_id, 0, "hello")
    append(env, runner, job_id, 1, "world", "stderr")
    with pytest.raises(PermissionDenied) as info:
        env.core.read_log(env.viewer, job_id=job_id)
    assert P.JOB_READ_OUTPUT in info.value.required or "job.read_output" in info.value.required
    page = env.core.read_log(reader(), job_id=job_id)
    assert [c.text for c in page.chunks] == ["hello", "world"]
    assert page.next_seq == 2
    assert not page.complete  # ジョブは実行中
    reads = [r for r in env.audit() if r.operation is AuditOperation.LOG_READ and r.outcome is AuditOutcome.SUCCEEDED]
    assert len(reads) == 1 and reads[0].actor == "reader"
    assert "hello" not in repr(reads[0])  # 内容を記録しない
    assert any(d.operation is AuditOperation.LOG_READ for d in env.denied())


def test_read_log_pages_with_after_seq_and_complete_flag(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    for seq in range(5):
        append(env, runner, job_id, seq, f"l{seq}")
    env.finish(runner, job_id)
    first = env.core.read_log(reader(), job_id=job_id, limit=2)
    assert [c.seq for c in first.chunks] == [0, 1] and not first.complete
    rest = env.core.read_log(reader(), job_id=job_id, after_seq=first.next_seq - 1, limit=10)
    assert [c.seq for c in rest.chunks] == [2, 3, 4] and rest.complete
    with pytest.raises(ValidationFailed):
        env.core.read_log(reader(), job_id=job_id, limit=0)
    with pytest.raises(JobNotFound):
        env.core.read_log(reader(), job_id="nope")


def test_list_artifacts_requires_permission_and_is_audited(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    env.core.report_finished(
        runner.principal, runner_id=runner.runner_id, job_id=job_id, outcome=JobState.SUCCEEDED, artifacts=[ref()]
    )
    with pytest.raises(PermissionDenied):
        env.core.list_artifacts(env.viewer, job_id=job_id)
    assert env.core.list_artifacts(reader(), job_id=job_id) == (ref(),)
    assert [r for r in env.audit() if r.operation is AuditOperation.ARTIFACT_READ]
    assert all(r.outcome in (AuditOutcome.SUCCEEDED, AuditOutcome.DENIED) for r in env.audit())


# ---------------------------------------------------------------- 中断の指示(T049)と、リース切れの失敗の確定(T055)


def operator() -> Principal:
    return Principal.of("op", {P.GENERAL, P.FORCE_ABORT})


def test_heartbeat_reports_abort_request_only_for_the_assigned_job(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    other = env.runner("r-b", {})
    assert env.heartbeat(runner).abort_requested is False
    env.core.cancel(operator(), job_id=job_id, reason="stop it")
    assert env.heartbeat(runner).abort_requested is True
    assert env.heartbeat(other).abort_requested is False  # 他のランナーには伝わらない
    registered = env.core.register_runner(runner.principal, runner_id=runner.runner_id, capabilities={})
    assert registered.abort_requested is True
    env.core.confirm_stopped(runner.principal, runner_id=runner.runner_id, job_id=job_id)
    assert env.heartbeat(runner).abort_requested is False


def test_sweep_fails_expired_job_without_requeue_and_emits_completion_event(env: RunnerEnv) -> None:
    runner, job_id = running(env)
    env.advance(181)
    env.core.sweep_runners(env.sweeper)
    job = env.job(job_id)
    assert job.state is JobState.FAILED and job.result_detail is not None
    assert job.result_detail.failure_reason == "lease_expired"
    assert env.queue_ids() == []
    with env.core.new_uow() as uow:
        events = uow.outbox.fetch_pending(10)
    assert [(e.event.job_id, e.event.state) for e in events if e.event.job_id == job_id] == [(job_id, JobState.FAILED)]
    complete = [r for r in env.audit(job_id=job_id) if r.operation is AuditOperation.COMPLETE]
    assert complete[0].actor == "sweeper" and complete[0].after["failure_reason"] == "lease_expired"
    again = env.core.sweep_runners(env.sweeper)  # 冪等
    assert again.leases_expired == 0
    with pytest.raises(Exception, match="failed から finish"):
        env.finish(runner, job_id)


def test_purge_removes_logs_and_artifact_refs_with_the_job_and_keeps_others(env: RunnerEnv) -> None:
    from datetime import timedelta

    from job_core.job.domain.retention import RetentionPolicy

    runner, old_job = running(env)
    append(env, runner, old_job, 0, "old-log")
    env.core.report_finished(
        runner.principal, runner_id=runner.runner_id, job_id=old_job, outcome=JobState.SUCCEEDED, artifacts=[ref()]
    )
    env.advance(60 * 60 * 24 * 400)
    env.heartbeat(runner)
    new_job = env.submit().job_id
    assert env.request(runner).assignment is not None
    append(env, runner, new_job, 0, "new-log")
    purger = Principal.of("purger", {P.RETENTION_PURGE})
    result = env.core.purge(purger, policy=RetentionPolicy(job_retention=timedelta(days=365)))
    assert result.jobs_deleted == 1
    assert env.core.outputs.read(old_job, -1, 10) == [] and env.core.outputs.list_artifacts(old_job) == []  # type: ignore[arg-type]
    assert [c.text for c in env.core.outputs.read(new_job, -1, 10)] == ["new-log"]  # type: ignore[arg-type]
