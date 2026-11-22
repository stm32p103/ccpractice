"""runner の権限の判定の網羅テスト(spec SC-009、FR-025、FR-026。research.md R10)。

13 権限の全部分集合(8192 通り)× ユースケースについて、contracts/application-api.md の必要な権限から独立に
書いた期待値と一致することを検査する。Principal.kind を変えても結果が変わらないこと(憲章 原則 9)も検査する。
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.domain.errors import PermissionDenied, RunnerMismatch
from job_core.runner.application import authorization as authz
from job_core.runner.domain.errors import RunnerIdentityMismatch
from job_core.shared.ids import RunnerId, SubjectId

ALL_SUBSETS = [frozenset(combo) for size in range(len(P) + 1) for combo in itertools.combinations(list(P), size)]

REQUIRED: dict[str, frozenset[P]] = {
    "manage": frozenset({P.RUNNER_MANAGE}),
    "report": frozenset({P.RUNNER_REPORT}),
    "request_job": frozenset({P.RUNNER_REPORT, P.JOB_EXECUTE}),
    "sweep": frozenset({P.RUNNER_SWEEP}),
    "view": frozenset({P.GENERAL}),
}

CALLS: dict[str, Callable[[Principal], None]] = {
    "manage": authz.authorize_manage,
    "report": authz.authorize_report,
    "request_job": authz.authorize_request_job,
    "sweep": authz.authorize_sweep,
    "view": authz.authorize_view,
}


def allowed(operation: str, principal: Principal) -> bool:
    try:
        CALLS[operation](principal)
    except PermissionDenied as denial:
        assert denial.required, "拒否には必要な権限を含める"
        assert set(denial.required) <= {p.value for p in REQUIRED[operation]}
        return False
    return True


def test_subset_count() -> None:
    assert len(P) == 13
    assert len(ALL_SUBSETS) == 8192


@pytest.mark.parametrize("operation", list(CALLS))
def test_every_permission_combination(operation: str) -> None:
    mismatches = []
    for perms in ALL_SUBSETS:
        principal = Principal(SubjectId("me"), perms)
        if allowed(operation, principal) != (REQUIRED[operation] <= perms):
            mismatches.append(sorted(p.value for p in perms))
    assert mismatches == []


@pytest.mark.parametrize("operation", list(CALLS))
def test_principal_kind_does_not_affect_decision(operation: str) -> None:
    for perms in ALL_SUBSETS[::7]:
        results = {allowed(operation, Principal(SubjectId("me"), perms, kind)) for kind in PrincipalKind}
        assert len(results) == 1


def test_runner_manage_and_audit_read_all_are_independent() -> None:
    manager = Principal(SubjectId("me"), frozenset({P.RUNNER_MANAGE}))
    auditor = Principal(SubjectId("me"), frozenset({P.AUDIT_READ_ALL}))
    assert allowed("manage", manager) and not allowed("manage", auditor)
    assert not allowed("view", manager) and not allowed("view", auditor)
    from job_core.job.application import authorization as job_authz

    job_authz.authorize_audit_read_all(auditor)
    with pytest.raises(PermissionDenied):
        job_authz.authorize_audit_read_all(manager)


def test_request_job_needs_both_runner_report_and_job_execute() -> None:
    assert not allowed("request_job", Principal(SubjectId("me"), frozenset({P.RUNNER_REPORT})))
    assert not allowed("request_job", Principal(SubjectId("me"), frozenset({P.JOB_EXECUTE})))
    assert allowed("request_job", Principal(SubjectId("me"), frozenset({P.RUNNER_REPORT, P.JOB_EXECUTE})))


def test_require_self() -> None:
    principal = Principal(SubjectId("R1"), frozenset())
    authz.require_self(principal, RunnerId("R1"))
    with pytest.raises(RunnerMismatch) as err:
        authz.require_self(principal, RunnerId("R2"))
    assert isinstance(err.value, RunnerIdentityMismatch)
    assert err.value.code == "runner_mismatch"
