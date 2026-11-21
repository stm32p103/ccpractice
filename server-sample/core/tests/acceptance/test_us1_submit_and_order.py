"""US1 — ジョブを提出し、並んだ順に実行される(spec US1-1〜US1-7 とエッジケース)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import PrincipalKind
from job_core.job.application import (
    AuditOperation,
    DuplicateQueuedJob,
    JobNotFound,
    JobState,
    NoEligibleRunner,
    PermissionDenied,
    RunnerBusy,
    RunnerMismatch,
    ValidationFailed,
)

from .conftest import Env, principal


def test_us1_1_rejected_when_no_runner_can_satisfy(env: Env) -> None:
    with pytest.raises(NoEligibleRunner):
        env.submit(requirement={"os": "none"})
    assert env.queue_ids() == []


def test_us1_2_accepted_and_queued_at_tail(env: Env) -> None:
    first = env.submit()
    second = env.submit()
    assert (first.position, second.position) == (1, 2)
    assert env.queue_ids() == [first.job_id, second.job_id]
    assert env.job(second.job_id).state is JobState.QUEUED
    env.assert_consistent()


def test_us1_3_assigned_in_queue_order(env: Env) -> None:
    a, b = env.submit_many(2)
    assert env.assign() == a
    env.finish(a)
    assert env.assign() == b


def test_us1_4_runner_runs_one_job_at_a_time(env: Env) -> None:
    a, b = env.submit_many(2)
    assert env.assign() == a
    with pytest.raises(RunnerBusy) as busy:
        env.assign()
    assert busy.value.job_id == a
    assert env.job(b).state is JobState.QUEUED
    env.finish(a)
    assert env.assign() == b


def test_us1_5_free_runner_takes_first_job_it_can_run(env: Env) -> None:
    head = env.submit(requirement={"os": "x"}).job_id  # R1 だけが実行できる
    later = env.submit(requirement={"os": "y"}).job_id  # R2 だけが実行できる
    assert env.assign(env.runner2, "R2") == later
    assert env.queue_ids() == [head]


def test_us1_6_duplicate_of_queued_job_is_rejected(env: Env) -> None:
    first = env.submit(source="repo", revision="abc").job_id
    with pytest.raises(DuplicateQueuedJob) as duplicate:
        env.submit(source="repo", revision="abc", payload={"different": True})
    assert duplicate.value.existing_job_id == first
    # 実行中・終了済みなら受け付ける
    env.run(first)
    second = env.submit(source="repo", revision="abc").job_id
    assert second != first


def test_us1_6_same_content_from_other_submitter_is_also_duplicate(env: Env) -> None:
    first = env.submit(source="repo", revision="abc").job_id
    with pytest.raises(DuplicateQueuedJob) as duplicate:
        env.submit(env.bob, source="repo", revision="abc")
    assert duplicate.value.existing_job_id == first


def test_us1_6_jobs_without_source_are_not_checked_for_duplicates(env: Env) -> None:
    env.submit()
    env.submit()
    assert len(env.queue_ids()) == 2


def test_us1_6_different_revision_or_type_is_not_duplicate(env: Env) -> None:
    env.submit(source="repo", revision="abc")
    env.submit(source="repo", revision="def")
    env.submit(source="repo", revision="abc", job_type="type-b")
    assert len(env.queue_ids()) == 3


def test_us1_7_submitter_without_permission_is_rejected_and_audited(env: Env) -> None:
    with pytest.raises(PermissionDenied) as denial:
        env.submit(env.viewer)
    assert denial.value.required == ("job.submit",)
    assert env.queue_ids() == []
    denied = env.denied_records()
    assert len(denied) == 1
    assert denied[0].operation is AuditOperation.SUBMIT
    assert denied[0].actor == "viewer"


@pytest.mark.parametrize("missing", ["job_type", "requirement", "payload", "timeout"])
def test_edge_missing_required_field_is_rejected(env: Env, missing: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        env.submit(**{missing: None})
    assert error.value.field == missing
    assert env.queue_ids() == []


@pytest.mark.parametrize("timeout", [timedelta(0), timedelta(seconds=-5)])
def test_edge_non_positive_timeout_is_rejected(env: Env, timeout: timedelta) -> None:
    with pytest.raises(ValidationFailed):
        env.submit(timeout=timeout)


def test_edge_payload_is_kept_as_is(env: Env) -> None:
    payload = {"nested": {"list": [1, "two", None, True]}, "unicode": "日本語"}
    job_id = env.submit(payload=payload).job_id
    assert env.job(job_id).definition.payload.value == payload


def test_edge_job_stays_queued_after_runners_unregister(env: Env) -> None:
    job_id = env.submit().job_id
    env.core.runners.unregister("R1")
    assert env.job(job_id).state is JobState.QUEUED
    assert env.queue_ids() == [job_id]


def test_edge_on_behalf_requires_permission(env: Env) -> None:
    with pytest.raises(PermissionDenied) as denial:
        env.submit(env.alice, on_behalf_of="bob")
    assert denial.value.required == ("job.submit_on_behalf",)


def test_edge_on_behalf_records_both_principals(env: Env) -> None:
    result = env.submit(env.service, on_behalf_of="carol")
    job = env.job(result.job_id)
    assert (job.submitter.owner, job.submitter.submitted_by) == ("carol", "svc")
    history = env.core.get_job_history(env.viewer, job_id=result.job_id)
    assert history[0].actor == "svc"
    assert history[0].on_behalf_of == "carol"


def test_edge_many_jobs_from_one_submitter_are_accepted(env: Env) -> None:
    env.submit_many(600)
    assert len(env.queue_ids()) == 600  # 上限を設けない(FR-007)


def test_edge_report_from_unassigned_runner_is_rejected_and_audited(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    with pytest.raises(RunnerMismatch):
        env.core.report_finished(env.runner2, runner_id="R2", job_id=job_id, outcome="succeeded")
    assert env.job(job_id).state is JobState.RUNNING
    denied = env.denied_records()
    assert [(r.operation, r.denial_code) for r in denied] == [(AuditOperation.COMPLETE, "runner_mismatch")]


def test_edge_runner_operations_require_execute_permission_regardless_of_kind(env: Env) -> None:
    job_id = env.submit().job_id
    fake_runner = principal("runner-x", {P.GENERAL}, PrincipalKind.RUNNER)
    with pytest.raises(PermissionDenied):
        env.core.assign(fake_runner, runner_id="R1")
    env.run(job_id)
    with pytest.raises(PermissionDenied):
        env.core.report_finished(fake_runner, runner_id="R1", job_id=job_id, outcome="succeeded")
    assert env.job(job_id).state is JobState.RUNNING


def test_edge_report_for_unknown_job(env: Env) -> None:
    with pytest.raises(JobNotFound):
        env.core.report_finished(env.runner1, runner_id="R1", job_id="nope", outcome="failed")


def test_edge_report_validates_outcome_and_summary(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    with pytest.raises(ValidationFailed):
        env.core.report_finished(env.runner1, runner_id="R1", job_id=job_id, outcome="cancelled")
    with pytest.raises(ValidationFailed):
        env.core.report_finished(
            env.runner1, runner_id="R1", job_id=job_id, outcome="failed", result_summary="x" * 1025
        )
    env.core.report_finished(env.runner1, runner_id="R1", job_id=job_id, outcome="failed", result_summary="exit 2")
    job = env.job(job_id)
    assert job.state is JobState.FAILED
    assert job.result_summary is not None and job.result_summary.value == "exit 2"


def test_edge_successful_operations_are_audited(env: Env) -> None:
    job_id = env.submit().job_id
    env.run(job_id)
    env.finish(job_id)
    operations = [r.operation for r in env.core.get_job_history(env.viewer, job_id=job_id)]
    assert operations == [AuditOperation.SUBMIT, AuditOperation.ASSIGN, AuditOperation.COMPLETE]
