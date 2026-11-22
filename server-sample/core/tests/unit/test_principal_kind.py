"""PrincipalKind.ANONYMOUS(003)。可否の判定に kind が使われないこと(憲章 原則 9)。"""

from __future__ import annotations

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal, PrincipalKind
from job_core.job.application import authorization as authz
from job_core.job.domain.errors import PermissionDenied
from job_core.shared.ids import SubjectId


def test_anonymous_kind_exists_and_has_no_permissions_by_default() -> None:
    p = Principal.of("unauthenticated", kind=PrincipalKind.ANONYMOUS)
    assert p.kind is PrincipalKind.ANONYMOUS
    assert p.permissions == frozenset()


@pytest.mark.parametrize("kind", list(PrincipalKind))
def test_decision_does_not_depend_on_kind(kind: PrincipalKind) -> None:
    allowed = Principal.of("a", [P.JOB_SUBMIT], kind)
    denied = Principal.of("a", [], kind)
    authz.authorize_submit(allowed, owner=SubjectId("a"), placed=False)
    with pytest.raises(PermissionDenied):
        authz.authorize_submit(denied, owner=SubjectId("a"), placed=False)


def test_access_manage_is_a_permission() -> None:
    assert P("access.manage") is P.ACCESS_MANAGE
    assert len(P) == 13
