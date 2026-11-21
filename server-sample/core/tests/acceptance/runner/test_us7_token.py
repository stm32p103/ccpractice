"""US7: ランナーのトークンを発行・失効する(spec US7-1〜US7-4、FR-022〜FR-025)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.permission import Permission
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import PermissionDenied
from job_core.runner.application import RunnerAuthenticationFailed, RunnerIdentityMismatch, RunnerNotFound

from .conftest import RunnerEnv, requirement


def test_us7_1_revoked_token_is_rejected_by_authentication(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.revoke_token(env.admin, runner_id=runner.runner_id, reason="漏えいの疑い")
    with pytest.raises(RunnerAuthenticationFailed):
        env.core.authenticate_runner(runner.token)
    record = next(r for r in env.audit() if r.operation is AuditOperation.TOKEN_REVOKE)
    assert record.reason == "漏えいの疑い"
    assert runner.token not in repr(record)
    denied = [d for d in env.denied() if d.operation is AuditOperation.RUNNER_AUTHENTICATE]
    assert len(denied) == 1 and denied[0].denial_code == "authentication_failed"
    assert denied[0].runner_id == runner.runner_id


def test_us7_2_reissue_returns_new_token_once_and_old_stays_invalid(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    new = env.core.reissue_token(env.admin, runner_id=runner.runner_id)
    assert new.value != runner.token
    assert new.token_id
    principal = env.core.authenticate_runner(new.value)
    assert principal.subject_id == runner.runner_id
    env.core.register_runner(principal, runner_id=runner.runner_id, capabilities={"k1": "a"})
    with pytest.raises(RunnerAuthenticationFailed):
        env.core.authenticate_runner(runner.token)
    ops = [r.operation for r in env.audit() if r.runner_id == runner.runner_id]
    assert ops.count(AuditOperation.TOKEN_ISSUE) == 2
    assert ops.count(AuditOperation.TOKEN_REVOKE) == 1


def test_reissue_after_revoke_works(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.revoke_token(env.admin, runner_id=runner.runner_id)
    new = env.core.reissue_token(env.admin, runner_id=runner.runner_id)
    env.core.authenticate_runner(new.value)
    with pytest.raises(RunnerAuthenticationFailed):
        env.core.authenticate_runner(runner.token)


def test_revoke_without_valid_token_changes_nothing(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.revoke_token(env.admin, runner_id=runner.runner_id)
    count = len(env.audit())
    env.core.revoke_token(env.admin, runner_id=runner.runner_id)
    assert len(env.audit()) == count


def test_us7_3_token_value_is_never_shown_again(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    shown = [
        repr(env.core.list_runners(env.viewer)),
        repr(env.core.get_runner(env.viewer, runner_id=runner.runner_id)),
        repr(env.core.get_runner_history(env.viewer, runner_id=runner.runner_id)),
        repr(env.audit(limit=1) if False else env.core.get_audit_log(env.auditor, limit=1000)),
    ]
    for text in shown:
        assert runner.token not in text


def test_us7_4_token_of_another_runner_is_rejected_for_every_runner_operation(env: RunnerEnv) -> None:
    a = env.runner("r-a", {})
    b = env.runner("r-b", {})
    env.submit()
    calls = [
        lambda: env.core.heartbeat(a.principal, runner_id=b.runner_id),
        lambda: env.core.register_runner(a.principal, runner_id=b.runner_id, capabilities={}),
        lambda: env.core.request_job(a.principal, runner_id=b.runner_id),
        lambda: env.core.report_fault(a.principal, runner_id=b.runner_id, description="e1"),
        lambda: env.core.report_recovered(a.principal, runner_id=b.runner_id),
    ]
    for call in calls:
        with pytest.raises(RunnerIdentityMismatch):
            call()
    mismatches = [d for d in env.denied() if d.denial_code == "runner_mismatch"]
    assert len(mismatches) == len(calls)
    assert all(d.runner_id == b.runner_id and d.actor == a.runner_id for d in mismatches)
    assert env.state(b.runner_id) == "online"


def test_fr025_runner_token_cannot_do_anything_but_runner_operations(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    principal = runner.principal
    assert principal.permissions == {Permission.RUNNER_REPORT, Permission.JOB_EXECUTE}
    refusals = [
        lambda: env.core.create_runner(principal, name="x"),
        lambda: env.core.delete_runner(principal, runner_id=runner.runner_id),
        lambda: env.core.set_maintenance(principal, runner_id=runner.runner_id),
        lambda: env.core.clear_maintenance(principal, runner_id=runner.runner_id),
        lambda: env.core.clear_fault(principal, runner_id=runner.runner_id),
        lambda: env.core.reissue_token(principal, runner_id=runner.runner_id),
        lambda: env.core.revoke_token(principal, runner_id=runner.runner_id),
        lambda: env.core.replace_allowlist(principal, entries={}),
        lambda: env.core.sweep_runners(principal),
        lambda: env.core.submit(
            principal, job_type="t", requirement=requirement(), payload={}, timeout=timedelta(minutes=1)
        ),
        lambda: env.core.list_runners(principal),  # 閲覧は job.general。トークンには付かない
    ]
    for call in refusals:
        with pytest.raises(PermissionDenied):
            call()


def test_concurrent_reissue_and_authentication_old_token_fails_after_commit(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    results: dict[str, object] = {}
    # 再発行の確定の直前に、旧トークンでの認証が割り込む(この時点では、まだ有効)
    env.core.store.inject_before_next_commit(
        lambda: results.setdefault("during", env.core.authenticate_runner(runner.token))
    )
    new = env.core.reissue_token(env.admin, runner_id=runner.runner_id)
    assert "during" in results
    with pytest.raises(RunnerAuthenticationFailed):  # 確定の後は通らない
        env.core.authenticate_runner(runner.token)
    env.core.authenticate_runner(new.value)


def test_concurrent_reissues_leave_exactly_one_valid_token(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    issued: list[str] = []
    env.core.store.inject_before_next_commit(
        lambda: issued.append(env.core.reissue_token(env.admin, runner_id=runner.runner_id).value)
    )
    issued.append(env.core.reissue_token(env.admin, runner_id=runner.runner_id).value)
    valid = 0
    for value in [runner.token, *issued]:
        try:
            env.core.authenticate_runner(value)
            valid += 1
        except RunnerAuthenticationFailed:
            pass
    assert valid == 1


def test_token_operations_on_unknown_runner(env: RunnerEnv) -> None:
    with pytest.raises(RunnerNotFound):
        env.core.reissue_token(env.admin, runner_id="nope")
    with pytest.raises(RunnerNotFound):
        env.core.revoke_token(env.admin, runner_id="nope")


@pytest.mark.parametrize("bad", ["", "rt_", "garbage", "rt_" + "x" * 43])
def test_unknown_token_is_rejected_and_audited_without_the_value(env: RunnerEnv, bad: str) -> None:
    with pytest.raises(RunnerAuthenticationFailed):
        env.core.authenticate_runner(bad)
    denied = env.denied()
    assert denied[-1].operation is AuditOperation.RUNNER_AUTHENTICATE
    assert bad not in repr(denied[-1]) or bad == ""
    assert denied[-1].runner_id is None
