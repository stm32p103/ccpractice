"""監査の網羅(spec FR-028、FR-029、SC-010)と、ランナーごとの経緯の閲覧範囲(001 FR-026 に倣う)。

状態を変えるすべてのユースケースの成功と拒否が、runner_id 付きで監査ログに残り、001 の GetAuditLog で runner_id の
条件で取り出せる。生存通知そのもの(状態が変わらない通知)は記録されない。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from job_core.job.domain.audit import AuditOperation, AuditOutcome
from job_core.job.domain.errors import PermissionDenied
from job_core.runner.application import RunnerNotFound

from .conftest import RunnerEnv

Op = AuditOperation


def test_every_successful_state_change_is_recorded_with_runner_id(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "a"})
    job = env.submit().job_id
    env.request(runner)
    env.heartbeat(runner)  # 状態が変わらない生存通知は記録されない
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e1")
    env.core.report_recovered(runner.principal, runner_id=runner.runner_id)
    env.core.report_fault(runner.principal, runner_id=runner.runner_id, description="e2")
    env.core.clear_fault(env.admin, runner_id=runner.runner_id)
    env.core.set_maintenance(env.admin, runner_id=runner.runner_id, reason="m")
    env.core.clear_maintenance(env.admin, runner_id=runner.runner_id)
    env.advance(200)
    env.core.sweep_runners(env.sweeper)  # RUNNER_OFFLINE、LEASE_EXPIRED
    env.heartbeat(runner)  # RUNNER_ONLINE
    env.core.reissue_token(env.admin, runner_id=runner.runner_id)  # TOKEN_REVOKE、TOKEN_ISSUE
    env.core.revoke_token(env.admin, runner_id=runner.runner_id)
    env.finish(runner, job)
    env.core.delete_runner(env.admin, runner_id=runner.runner_id)  # RUNNER_DELETE(トークンは失効済み)

    records = env.audit(runner_id=runner.runner_id)
    operations = {r.operation for r in records}
    assert operations >= {
        Op.RUNNER_CREATE,
        Op.TOKEN_ISSUE,
        Op.RUNNER_REGISTER,
        Op.RUNNER_ONLINE,
        Op.ASSIGN,
        Op.FAULT_REPORT,
        Op.FAULT_RECOVERED,
        Op.FAULT_CLEAR,
        Op.RUNNER_MAINTENANCE_SET,
        Op.RUNNER_MAINTENANCE_CLEAR,
        Op.RUNNER_OFFLINE,
        Op.LEASE_EXPIRED,
        Op.TOKEN_REVOKE,
        Op.RUNNER_DELETE,
    }
    assert Op.RUNNER_HEARTBEAT not in operations
    for record in records:
        assert record.runner_id == runner.runner_id
        assert record.actor
        assert record.occurred_at
        assert record.outcome is AuditOutcome.SUCCEEDED
    assert [r.occurred_at for r in records] == sorted(r.occurred_at for r in records)
    # 許可リストの変更は、ランナーに属さない
    assert any(r.operation is Op.ALLOWLIST_CHANGE and r.runner_id is None for r in env.audit())


def test_registration_audit_has_before_and_after_of_capabilities(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {"k1": "a"})
    env.core.register_runner(runner.principal, runner_id=runner.runner_id, capabilities={"set1": ["x"]})
    registers = [r for r in env.audit(runner_id=runner.runner_id) if r.operation is Op.RUNNER_REGISTER]
    assert registers[-1].before["capabilities"] == {"k1": "a"}
    assert registers[-1].after["capabilities"] == {"set1": ["x"]}


DENIAL_CASES: list[tuple[str, Callable[[RunnerEnv, str], Any], AuditOperation]] = [
    ("create", lambda e, rid: e.core.create_runner(e.nobody, name="x"), Op.RUNNER_CREATE),
    ("allowlist", lambda e, rid: e.core.replace_allowlist(e.nobody, entries={}), Op.ALLOWLIST_CHANGE),
    ("maintenance", lambda e, rid: e.core.set_maintenance(e.nobody, runner_id=rid), Op.RUNNER_MAINTENANCE_SET),
    ("unmaintenance", lambda e, rid: e.core.clear_maintenance(e.nobody, runner_id=rid), Op.RUNNER_MAINTENANCE_CLEAR),
    ("clear_fault", lambda e, rid: e.core.clear_fault(e.nobody, runner_id=rid), Op.FAULT_CLEAR),
    ("delete", lambda e, rid: e.core.delete_runner(e.nobody, runner_id=rid), Op.RUNNER_DELETE),
    ("reissue", lambda e, rid: e.core.reissue_token(e.nobody, runner_id=rid), Op.TOKEN_ISSUE),
    ("revoke", lambda e, rid: e.core.revoke_token(e.nobody, runner_id=rid), Op.TOKEN_REVOKE),
    ("sweep", lambda e, rid: e.core.sweep_runners(e.nobody), Op.RUNNER_SWEEP),
    ("register", lambda e, rid: e.core.register_runner(e.nobody, runner_id=rid, capabilities={}), Op.RUNNER_REGISTER),
    ("heartbeat", lambda e, rid: e.core.heartbeat(e.nobody, runner_id=rid), Op.RUNNER_HEARTBEAT),
    ("request", lambda e, rid: e.core.request_job(e.nobody, runner_id=rid), Op.ASSIGN),
    ("fault", lambda e, rid: e.core.report_fault(e.nobody, runner_id=rid, description="e"), Op.FAULT_REPORT),
    ("recovered", lambda e, rid: e.core.report_recovered(e.nobody, runner_id=rid), Op.FAULT_RECOVERED),
]


@pytest.mark.parametrize(("name", "call", "operation"), DENIAL_CASES, ids=[c[0] for c in DENIAL_CASES])
def test_every_permission_denial_is_recorded(
    env: RunnerEnv, name: str, call: Callable[[RunnerEnv, str], Any], operation: AuditOperation
) -> None:
    runner = env.runner("r-a", {})
    before = len(env.denied())
    with pytest.raises(PermissionDenied):
        call(env, runner.runner_id)
    denied = env.denied()
    assert len(denied) == before + 1
    record = denied[-1]
    assert record.operation is operation
    assert record.outcome is AuditOutcome.DENIED
    assert record.denial_code == "permission_denied"
    assert record.actor == "nobody"
    if name not in {"create", "allowlist", "sweep"}:
        assert record.runner_id == runner.runner_id


def test_authentication_failures_are_recorded(env: RunnerEnv) -> None:
    from job_core.runner.application import RunnerAuthenticationFailed

    with pytest.raises(RunnerAuthenticationFailed):
        env.core.authenticate_runner("rt_nope")
    assert env.denied()[-1].operation is Op.RUNNER_AUTHENTICATE


# ---------------------------------------------------------------------- 閲覧範囲(spec FR-029)


def test_runner_history_is_visible_to_everyone_but_only_succeeded_records(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    with pytest.raises(PermissionDenied):
        env.core.set_maintenance(env.nobody, runner_id=runner.runner_id)  # 拒否の記録(履歴には出ない)
    env.core.set_maintenance(env.admin, runner_id=runner.runner_id)
    history = env.core.get_runner_history(env.viewer, runner_id=runner.runner_id)
    ops = [r.operation for r in history]
    assert ops == [Op.RUNNER_CREATE, Op.TOKEN_ISSUE, Op.RUNNER_REGISTER, Op.RUNNER_ONLINE, Op.RUNNER_MAINTENANCE_SET]
    assert all(r.outcome is AuditOutcome.SUCCEEDED for r in history)
    assert all(r.denial_code is None for r in history)
    assert [r.occurred_at for r in history] == sorted(r.occurred_at for r in history)


def test_runner_history_requires_view_permission_and_known_runner(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    with pytest.raises(PermissionDenied):
        env.core.get_runner_history(env.nobody, runner_id=runner.runner_id)
    with pytest.raises(RunnerNotFound):
        env.core.get_runner_history(env.viewer, runner_id="no-such-runner")


def test_runner_history_remains_after_deletion(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    env.core.delete_runner(env.admin, runner_id=runner.runner_id)
    history = env.core.get_runner_history(env.viewer, runner_id=runner.runner_id)
    assert Op.RUNNER_DELETE in [r.operation for r in history]


def test_denied_records_and_whole_audit_log_need_audit_read_all(env: RunnerEnv) -> None:
    runner = env.runner("r-a", {})
    with pytest.raises(PermissionDenied):
        env.core.set_maintenance(env.nobody, runner_id=runner.runner_id)
    # ランナー管理の権限(+ 閲覧)だけでは、拒否を含む監査ログ全体は見られない(001 の「管理」の権限は別)
    with pytest.raises(PermissionDenied):
        env.core.get_audit_log(env.admin)
    with pytest.raises(PermissionDenied):
        env.core.get_audit_log(env.viewer, runner_id=runner.runner_id)
    page = env.core.get_audit_log(env.auditor, runner_id=runner.runner_id, outcome="denied")
    assert [r.operation for r in page.items] == [Op.RUNNER_MAINTENANCE_SET]
    # 「管理」の権限だけでは、ランナーごとの経緯(job.general)は見られない
    with pytest.raises(PermissionDenied):
        env.core.get_runner_history(env.auditor, runner_id=runner.runner_id)
