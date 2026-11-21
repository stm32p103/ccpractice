"""US1: ランナーを作成し、ランナーが起動時に登録する(spec US1-1〜US1-6、FR-001〜FR-006、FR-027)。"""

from __future__ import annotations

import pytest

from job_core.job.domain.audit import AuditOperation, AuditOutcome
from job_core.job.domain.errors import PermissionDenied, ValidationFailed
from job_core.runner.application import (
    DuplicateRunnerName,
    InvalidDeclaration,
    RunnerNotFound,
    RunnerState,
    ValueKind,
)

from .conftest import RunnerEnv


def test_us1_1_create_returns_id_token_once_and_offline_runner(env: RunnerEnv) -> None:
    created = env.create("r-a")
    assert created.runner_id
    assert created.token.value.startswith("rt_")
    view = env.core.get_runner(env.viewer, runner_id=created.runner_id)
    assert view.state is RunnerState.OFFLINE
    assert view.capabilities == {}
    assert view.registered_at is None
    assert view.last_seen_at is None
    records = [r for r in env.audit() if r.runner_id == created.runner_id]
    assert [r.operation for r in records] == [AuditOperation.RUNNER_CREATE, AuditOperation.TOKEN_ISSUE]
    assert records[0].after == {"name": "r-a"}
    assert records[0].actor == "admin"


def test_us1_2_duplicate_name_is_rejected(env: RunnerEnv) -> None:
    env.create("r-a")
    with pytest.raises(DuplicateRunnerName):
        env.create("r-a")
    assert [v.name for v in env.core.list_runners(env.viewer)] == ["r-a"]


def test_us1_3_register_sets_capabilities_and_goes_online(env: RunnerEnv) -> None:
    handle = env.runner("r-a", register=False)
    result = env.core.register_runner(
        handle.principal, runner_id=handle.runner_id, capabilities={"k1": "a", "set1": ["x", "y"]}
    )
    assert result.state is RunnerState.ONLINE
    assert result.lease_expires_at is None
    assert result.heartbeat_interval.total_seconds() == 30
    view = env.core.get_runner(env.viewer, runner_id=handle.runner_id)
    assert view.state is RunnerState.ONLINE
    assert view.capabilities == {"k1": "a", "set1": ["x", "y"]}
    register = next(r for r in env.audit() if r.operation is AuditOperation.RUNNER_REGISTER)
    assert register.before["capabilities"] == {}
    assert register.after["capabilities"] == {"k1": "a", "set1": ["x", "y"]}
    assert register.after["had_live_lease"] is False
    assert any(r.operation is AuditOperation.RUNNER_ONLINE for r in env.audit())


def test_us1_4_reregistration_replaces_capabilities(env: RunnerEnv) -> None:
    handle = env.runner("r-a", {"k1": "a", "set1": ["x"]})
    env.core.register_runner(handle.principal, runner_id=handle.runner_id, capabilities={"k2": "b"})
    view = env.core.get_runner(env.viewer, runner_id=handle.runner_id)
    assert view.capabilities == {"k2": "b"}
    registers = [r for r in env.audit() if r.operation is AuditOperation.RUNNER_REGISTER]
    assert registers[-1].before["capabilities"] == {"k1": "a", "set1": ["x"]}
    assert registers[-1].after["capabilities"] == {"k2": "b"}


def test_us1_5_key_outside_allowlist_is_rejected_and_audited(env: RunnerEnv) -> None:
    handle = env.runner("r-a", {"k1": "a"})
    before = env.core.get_runner(env.viewer, runner_id=handle.runner_id)
    env.advance(10)
    with pytest.raises(InvalidDeclaration) as err:
        env.core.register_runner(
            handle.principal, runner_id=handle.runner_id, capabilities={"k1": "z", "k9": "SECRET-VALUE"}
        )
    assert dict(err.value.violations) == {"k9": "not_allowed"}
    after = env.core.get_runner(env.viewer, runner_id=handle.runner_id)
    assert after.capabilities == before.capabilities == {"k1": "a"}  # 能力は変わらない
    assert after.last_seen_at == before.last_seen_at  # 最終応答時刻も変わらない
    denied = env.denied()
    assert len(denied) == 1
    assert denied[0].denial_code == "invalid_declaration"
    assert denied[0].runner_id == handle.runner_id
    assert "SECRET-VALUE" not in repr(denied[0])


def test_us1_5_kind_mismatch_and_bad_value_are_rejected(env: RunnerEnv) -> None:
    handle = env.runner("r-a", register=False)
    for bad in ({"k1": ["a"]}, {"set1": "x"}, {"k1": ""}, {"k1": 5}):
        with pytest.raises(InvalidDeclaration):
            env.core.register_runner(handle.principal, runner_id=handle.runner_id, capabilities=bad)
    assert env.core.get_runner(env.viewer, runner_id=handle.runner_id).registered_at is None


def test_us1_6_create_without_permission_is_denied_and_audited(env: RunnerEnv) -> None:
    for principal in (env.nobody, env.viewer, env.auditor, env.alice):
        with pytest.raises(PermissionDenied) as err:
            env.core.create_runner(principal, name="r-x")
        assert err.value.required == ("runner.manage",)
    assert env.core.list_runners(env.viewer) == ()
    denied = env.denied()
    assert len(denied) == 4
    assert {d.denial_code for d in denied} == {"permission_denied"}
    assert all(d.operation is AuditOperation.RUNNER_CREATE for d in denied)
    assert all(d.outcome is AuditOutcome.DENIED for d in denied)


def test_edge_empty_declaration_is_allowed_and_runner_is_registered(env: RunnerEnv) -> None:
    handle = env.runner("r-a", {})
    view = env.core.get_runner(env.viewer, runner_id=handle.runner_id)
    assert view.capabilities == {}
    assert view.state is RunnerState.ONLINE


def test_create_validates_name(env: RunnerEnv) -> None:
    for bad in ("", "   ", "a" * 129, "a\nb"):
        with pytest.raises(ValidationFailed):
            env.create(bad)


def test_register_unknown_runner(env: RunnerEnv) -> None:
    handle = env.runner("r-a", register=False)
    env.core.delete_runner(env.admin, runner_id=handle.runner_id)
    with pytest.raises(RunnerNotFound):
        env.core.register_runner(handle.principal, runner_id=handle.runner_id, capabilities={})


def test_list_runners_does_not_show_token_and_is_open_to_everyone_with_general(env: RunnerEnv) -> None:
    created = env.create("b-runner")
    env.create("a-runner")
    runners = env.core.list_runners(env.viewer)
    assert [r.name for r in runners] == ["a-runner", "b-runner"]  # 名前の順
    text = repr(runners)
    assert created.token.value not in text
    assert created.token.token_id not in text
    with pytest.raises(PermissionDenied):
        env.core.list_runners(env.nobody)


def test_allowlist_is_replaced_by_manage_permission_only_and_audited(env: RunnerEnv) -> None:
    entries = env.core.replace_allowlist(env.admin, entries={"k3": "set"}, reason="更新").entries
    assert dict(entries) == {"k3": ValueKind.SET}
    assert dict(env.core.get_allowlist(env.viewer).entries) == {"k3": ValueKind.SET}
    change = [r for r in env.audit() if r.operation is AuditOperation.ALLOWLIST_CHANGE][-1]
    assert change.before == {"entries": {"k1": "single", "k2": "single", "set1": "set"}}
    assert change.after == {"entries": {"k3": "set"}}
    assert change.reason == "更新"
    with pytest.raises(PermissionDenied):
        env.core.replace_allowlist(env.viewer, entries={})
    with pytest.raises(ValidationFailed):
        env.core.replace_allowlist(env.admin, entries={"BAD": "single"})


def test_allowlist_change_does_not_rewrite_existing_capabilities(env: RunnerEnv) -> None:
    handle = env.runner("r-a", {"k1": "a"})
    env.core.replace_allowlist(env.admin, entries={})
    assert env.core.get_runner(env.viewer, runner_id=handle.runner_id).capabilities == {"k1": "a"}
    with pytest.raises(InvalidDeclaration):  # 次の登録から効く
        env.core.register_runner(handle.principal, runner_id=handle.runner_id, capabilities={"k1": "a"})


def test_default_allowlist_is_empty_and_rejects_everything() -> None:
    from .conftest import make_env

    env = make_env(allowlist={})
    handle = env.runner("r-a", register=False)
    with pytest.raises(InvalidDeclaration):
        env.core.register_runner(handle.principal, runner_id=handle.runner_id, capabilities={"k1": "a"})
