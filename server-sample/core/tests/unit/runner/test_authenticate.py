"""AuthenticateRunner が返す主体の権限と、その主体でできないこと(spec FR-024、FR-025)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.permission import Permission
from job_core.access.principal import PrincipalKind
from job_core.job.domain.errors import PermissionDenied
from job_core.runner.application import RunnerAuthenticationFailed

from ...acceptance.runner.conftest import RunnerEnv, make_env


def test_authenticated_principal_has_exactly_two_permissions() -> None:
    env = make_env()
    runner = env.runner("r-a", {})
    principal = runner.principal
    assert principal.subject_id == runner.runner_id
    assert principal.kind is PrincipalKind.RUNNER
    assert principal.permissions == frozenset({Permission.RUNNER_REPORT, Permission.JOB_EXECUTE})


def test_runner_principal_cannot_manage_or_submit() -> None:
    env: RunnerEnv = make_env()
    runner = env.runner("r-a", {})
    p = runner.principal
    refusals = [
        lambda: env.core.create_runner(p, name="x"),
        lambda: env.core.delete_runner(p, runner_id=runner.runner_id),
        lambda: env.core.set_maintenance(p, runner_id=runner.runner_id),
        lambda: env.core.reissue_token(p, runner_id=runner.runner_id),
        lambda: env.core.revoke_token(p, runner_id=runner.runner_id),
        lambda: env.core.replace_allowlist(p, entries={}),
        lambda: env.core.submit(p, job_type="t", requirement={"all": []}, payload={}, timeout=timedelta(minutes=1)),
    ]
    for refusal in refusals:
        with pytest.raises(PermissionDenied):
            refusal()


def test_each_runner_gets_its_own_subject() -> None:
    env = make_env()
    a = env.runner("r-a", {})
    b = env.runner("r-b", {})
    assert a.principal.subject_id != b.principal.subject_id
    assert env.core.authenticate_runner(a.token).subject_id == a.runner_id


def test_non_string_or_empty_tokens_fail() -> None:
    env = make_env()
    for bad in ("", None, 5):
        with pytest.raises(RunnerAuthenticationFailed):
            env.core.authenticate_runner(bad)  # type: ignore[arg-type]
