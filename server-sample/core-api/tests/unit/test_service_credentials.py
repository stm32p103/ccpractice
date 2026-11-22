"""サービス用の認証情報のユースケース(research.md R4、R10、T-A1、T-A3)。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal
from job_core.job.application import AuditFilter, AuditOperation
from job_core.job.domain.errors import PermissionDenied, ValidationFailed
from job_core_api.access.config import AccessConfig
from job_core_api.access.credentials import CredentialNotFoundError, ServiceCredentials
from job_core_api.access.holder import AccessConfigHolder
from job_core_api.access.ports import DuplicateCredentialName
from job_testing.api_fakes import DEFAULT_ACCESS, InMemoryServiceCredentialRepository
from job_testing.core_fakes import build_core

ADMIN = Principal.of("admin", [P.ACCESS_MANAGE])
MEMBER = Principal.of("alice", [P.GENERAL, P.JOB_SUBMIT])


def make() -> tuple[ServiceCredentials, InMemoryServiceCredentialRepository, object]:
    core = build_core()
    repository = InMemoryServiceCredentialRepository()
    holder = AccessConfigHolder(AccessConfig.from_mapping(DEFAULT_ACCESS))
    return ServiceCredentials(core.deps, repository, holder), repository, core


def audit_records(core) -> list:  # type: ignore[no-untyped-def]
    with core.new_uow() as uow:
        return list(uow.audit.query(AuditFilter(), None, 1000).items)


def test_issue_returns_value_once_and_stores_only_the_hash() -> None:
    service, repository, _ = make()
    issued = service.issue(ADMIN, name="svc-a", permissions=["job.submit"])
    assert issued.value.startswith("st_") and "***" in repr(issued) and issued.value not in repr(issued)
    stored = repository.get(issued.credential_id)
    assert stored is not None and issued.value not in repr(stored) and stored.token_hash != issued.value
    assert issued.value not in repr(service.list_all(ADMIN))


def test_permissions_beyond_the_ceiling_are_rejected() -> None:
    service, _, _ = make()
    for bad in (["access.manage"], ["runner.manage"], ["job.execute"], ["audit.read_all"], ["no.such"]):
        with pytest.raises(ValidationFailed):
            service.issue(ADMIN, name=f"n-{bad[0]}", permissions=bad)


def test_duplicate_name_is_rejected_until_revoked() -> None:
    service, _, _ = make()
    first = service.issue(ADMIN, name="svc-a", permissions=[])
    with pytest.raises(DuplicateCredentialName):
        service.issue(ADMIN, name="svc-a", permissions=[])
    service.revoke(ADMIN, credential_id=first.credential_id)
    service.issue(ADMIN, name="svc-a", permissions=[])


def test_invalid_names_are_validation_failures() -> None:
    service, _, _ = make()
    for name in ("", "  ", "x" * 129, "bad\nname"):
        with pytest.raises(ValidationFailed):
            service.issue(ADMIN, name=name, permissions=[])


def test_without_manage_permission_every_operation_is_denied_and_recorded() -> None:
    service, _, core = make()
    issued = service.issue(ADMIN, name="svc-a", permissions=[])
    for call in (
        lambda: service.issue(MEMBER, name="x", permissions=[]),
        lambda: service.list_all(MEMBER),
        lambda: service.revoke(MEMBER, credential_id=issued.credential_id),
    ):
        with pytest.raises(PermissionDenied):
            call()
    denied = [r for r in audit_records(core) if r.denial is not None]
    assert len(denied) == 3 and all(r.denial.required == ("access.manage",) for r in denied)


def test_revoke_is_one_way_idempotent_and_unknown_is_not_found() -> None:
    service, repository, core = make()
    issued = service.issue(ADMIN, name="svc-a", permissions=[])
    service.revoke(ADMIN, credential_id=issued.credential_id)
    service.revoke(ADMIN, credential_id=issued.credential_id)
    assert repository.get(issued.credential_id).is_revoked  # type: ignore[union-attr]
    revokes = [r for r in audit_records(core) if r.operation is AuditOperation.SERVICE_CREDENTIAL_REVOKE]
    assert len(revokes) == 1
    with pytest.raises(CredentialNotFoundError):
        service.revoke(ADMIN, credential_id="unknown")


@settings(max_examples=40, deadline=None)
@given(name=st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs")), min_size=1, max_size=40))
def test_value_and_hash_never_appear_in_audit_or_listing(name: str) -> None:
    if not name.strip():
        return
    service, repository, core = make()
    try:
        issued = service.issue(ADMIN, name=name, permissions=["job.submit"])
    except ValidationFailed:
        return
    stored = repository.get(issued.credential_id)
    assert stored is not None
    service.revoke(ADMIN, credential_id=issued.credential_id)
    haystack = repr(audit_records(core)) + repr(service.list_all(ADMIN))
    assert issued.value not in haystack and stored.token_hash not in haystack
