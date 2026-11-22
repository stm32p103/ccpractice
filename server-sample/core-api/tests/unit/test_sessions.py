"""セッションのユースケース(research.md R5)。権限が保存されず導出されること、期限の判定。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal
from job_core.job.application import AuditFilter, AuditOperation
from job_core.job.domain.errors import PermissionDenied
from job_core_api.access.audit import AuthFailureAuditor
from job_core_api.access.authenticate import AuthenticationFailed
from job_core_api.access.config import AccessConfig
from job_core_api.access.holder import AccessConfigHolder
from job_core_api.access.sessions import SessionService
from job_core_api.settings import ApiSettings
from job_testing.api_fakes import DEFAULT_ACCESS, FakeIdentityProvider, InMemorySessionRepository
from job_testing.contracts.access_config import variant
from job_testing.core_fakes import build_core


def make(**settings_kwargs):  # type: ignore[no-untyped-def]
    core = build_core()
    settings = ApiSettings(**settings_kwargs)
    identity = FakeIdentityProvider()
    sessions = InMemorySessionRepository()
    holder = AccessConfigHolder(AccessConfig.from_mapping(DEFAULT_ACCESS))
    service = SessionService(
        deps=core.deps,
        settings=settings,
        identity=identity,
        sessions=sessions,
        access=holder,
        auditor=AuthFailureAuditor(core.deps, settings),
    )
    return service, sessions, identity, holder, core


def test_login_stores_groups_and_never_permissions() -> None:
    service, sessions, _, _, _ = make()
    logged_in = service.login({"subject": "u1", "groups": "g-member,g-viewer"}, source="s")
    stored = sessions.all()[0]
    assert stored.groups == {"g-member", "g-viewer"} and stored.subject_id == "u1"
    assert not hasattr(stored, "permissions")
    assert logged_in.value.startswith("ss_") and logged_in.value not in repr(stored) + repr(logged_in)


def test_expiry_fields_follow_the_settings() -> None:
    service, _, _, _, core = make(
        session_absolute_timeout=timedelta(hours=4), session_idle_timeout=timedelta(minutes=30)
    )
    logged_in = service.login({"subject": "u1"}, source="s")
    session = logged_in.session
    assert session.expires_at - session.created_at == timedelta(hours=4)
    now = core.clock.peek()
    assert session.is_active(now, timedelta(minutes=30))
    assert not session.is_active(now + timedelta(minutes=31), timedelta(minutes=30))
    assert not session.is_active(now + timedelta(hours=4), timedelta(hours=10))


def test_permissions_follow_the_current_mapping_not_the_login_time_mapping() -> None:
    service, _, _, holder, _ = make()
    session = service.login({"subject": "u1", "groups": "g-member"}, source="s").session
    assert holder.get().permissions_of(session.groups) == {P.GENERAL, P.JOB_SUBMIT}
    holder.replace(AccessConfig.from_mapping(variant(groups={"g-member": ["viewer"]})))
    assert holder.get().permissions_of(session.groups) == {P.GENERAL}


def test_rejected_identity_is_an_authentication_failure_and_is_audited() -> None:
    service, _, identity, _, core = make()
    identity.accept_unregistered = False
    with pytest.raises(AuthenticationFailed):
        service.login({"subject": "nobody"}, source="10.0.0.1")
    with core.new_uow() as uow:
        records = uow.audit.query(AuditFilter(operation=AuditOperation.AUTH_FAILED), None, 10).items
    assert len(records) == 1 and "nobody" not in repr(records)


def test_logout_revokes_and_is_audited() -> None:
    service, sessions, _, _, core = make()
    logged_in = service.login({"subject": "u1"}, source="s")
    service.logout(logged_in.session)
    assert sessions.all()[0].revoked_at is not None
    with core.new_uow() as uow:
        operations = [r.operation for r in uow.audit.query(AuditFilter(), None, 10).items]
    assert operations == [AuditOperation.LOGIN, AuditOperation.LOGOUT]


def test_revoke_all_needs_manage_permission_and_counts() -> None:
    service, sessions, _, _, core = make()
    for _ in range(3):
        service.login({"subject": "u1"}, source="s")
    service.login({"subject": "u2"}, source="s")
    with pytest.raises(PermissionDenied):
        service.revoke_all_of(Principal.of("u9", [P.GENERAL]), subject_id="u1")
    assert service.revoke_all_of(Principal.of("root", [P.ACCESS_MANAGE]), subject_id="u1") == 3
    assert sum(1 for s in sessions.all() if s.revoked_at is None) == 1
    with core.new_uow() as uow:
        denied = uow.audit.query(AuditFilter(), None, 20).items
    assert any(r.denial is not None and r.denial.required == ("access.manage",) for r in denied)
