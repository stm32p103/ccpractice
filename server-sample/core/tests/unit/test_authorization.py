"""権限の判定の網羅テスト(SC-006)。

9 権限の全部分集合(512 通り)× 所有(自分/他人)× 対象の状態 × 操作について、
contracts/application-api.md「可否の表」から独立に書いた期待値と一致することを検査する。
Principal.kind を変えても結果が変わらないこと(憲章 原則 9)も検査する。
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application import authorization as authz
from job_core.job.domain.errors import PermissionDenied
from job_core.job.domain.states import JobState
from job_core.shared.ids import SubjectId

ME = SubjectId("me")
OTHER = SubjectId("other")
ALL_SUBSETS = [frozenset(combo) for size in range(len(P) + 1) for combo in itertools.combinations(list(P), size)]


def expected(operation: str, perms: frozenset[P], own: bool, state: JobState) -> bool:
    """可否の表(contracts/application-api.md)をそのまま書き下したもの。"""
    if operation == "submit":
        return (P.JOB_SUBMIT if own else P.SUBMIT_ON_BEHALF) in perms
    if operation == "submit_placed":
        return (P.JOB_SUBMIT if own else P.SUBMIT_ON_BEHALF) in perms and P.QUEUE_SCHEDULE in perms
    if operation == "retry":
        return P.JOB_SUBMIT in perms
    if operation == "retry_placed":
        return P.JOB_SUBMIT in perms and P.QUEUE_SCHEDULE in perms
    if operation == "reschedule":
        return P.QUEUE_SCHEDULE in perms
    if operation == "cancel":
        if own:
            return P.GENERAL in perms
        if state is JobState.QUEUED:
            return P.CANCEL_QUEUED in perms
        if state is JobState.RUNNING:
            return P.FORCE_ABORT in perms
        # 他人の終了済み: どちらかの権限があれば判定を通る(その後、状態の規則で拒否される)
        return P.CANCEL_QUEUED in perms or P.FORCE_ABORT in perms
    if operation == "view":
        return P.GENERAL in perms
    if operation == "audit_read_all":
        return P.AUDIT_READ_ALL in perms
    if operation == "execute":
        return P.JOB_EXECUTE in perms
    if operation == "purge":
        return P.RETENTION_PURGE in perms
    raise AssertionError(operation)


def call(operation: str, principal: Principal, own: bool, state: JobState) -> None:
    owner = principal.subject_id if own else OTHER
    calls: dict[str, Callable[[], None]] = {
        "submit": lambda: authz.authorize_submit(principal, owner=owner, placed=False),
        "submit_placed": lambda: authz.authorize_submit(principal, owner=owner, placed=True),
        "retry": lambda: authz.authorize_retry(principal, placed=False),
        "retry_placed": lambda: authz.authorize_retry(principal, placed=True),
        "reschedule": lambda: authz.authorize_reschedule(principal),
        "cancel": lambda: authz.authorize_cancel(principal, owner=owner, state=state),
        "view": lambda: authz.authorize_view(principal),
        "audit_read_all": lambda: authz.authorize_audit_read_all(principal),
        "execute": lambda: authz.authorize_execute(principal),
        "purge": lambda: authz.authorize_purge(principal),
    }
    calls[operation]()


OPERATIONS = [
    "submit",
    "submit_placed",
    "retry",
    "retry_placed",
    "reschedule",
    "cancel",
    "view",
    "audit_read_all",
    "execute",
    "purge",
]


def allowed(operation: str, principal: Principal, own: bool, state: JobState) -> bool:
    try:
        call(operation, principal, own, state)
    except PermissionDenied as denial:
        assert denial.required, "拒否には必要な権限の候補を含める"
        return False
    return True


def test_subset_count() -> None:
    assert len(P) == 9
    assert len(ALL_SUBSETS) == 512


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("state", list(JobState))
@pytest.mark.parametrize("own", [True, False], ids=["own", "other"])
def test_every_permission_combination(operation: str, state: JobState, own: bool) -> None:
    mismatches = []
    for perms in ALL_SUBSETS:
        principal = Principal(ME, perms)
        if allowed(operation, principal, own, state) != expected(operation, perms, own, state):
            mismatches.append(sorted(p.value for p in perms))
    assert mismatches == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_principal_kind_does_not_affect_decision(operation: str) -> None:
    for perms in ALL_SUBSETS:
        results = {
            allowed(operation, Principal(ME, perms, kind), own, state)
            for kind in PrincipalKind
            for own in (True,)
            for state in (JobState.QUEUED,)
        }
        assert len(results) == 1


def test_runner_kind_without_execute_permission_is_denied() -> None:
    runner = Principal(SubjectId("runner-1"), frozenset(), PrincipalKind.RUNNER)
    with pytest.raises(PermissionDenied) as denial:
        authz.authorize_execute(runner)
    assert denial.value.required == ("job.execute",)


def test_admin_permission_does_not_include_others() -> None:
    admin = Principal(ME, frozenset({P.AUDIT_READ_ALL}))
    for operation in OPERATIONS:
        if operation != "audit_read_all":
            assert not allowed(operation, admin, False, JobState.QUEUED)
