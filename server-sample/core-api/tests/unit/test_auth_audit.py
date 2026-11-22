"""認証失敗の監査と抑制(research.md R10、T-A1、T-A7)。"""

from __future__ import annotations

from datetime import timedelta

from job_core.access.principal import PrincipalKind
from job_core.job.application import AuditFilter, AuditOperation
from job_core_api.access.audit import AuthFailureAuditor
from job_core_api.settings import ApiSettings
from job_testing.core_fakes import CoreFixture, build_core


def failures(core: CoreFixture) -> list:  # type: ignore[type-arg]
    with core.new_uow() as uow:
        page = uow.audit.query(AuditFilter(operation=AuditOperation.AUTH_FAILED), None, 1000)
        return list(page.items)


def test_first_failure_is_recorded_as_anonymous() -> None:
    core = build_core()
    auditor = AuthFailureAuditor(core.deps, ApiSettings())
    auditor.record("10.0.0.1", "session")
    [record] = failures(core)
    assert record.actor == "unauthenticated"
    assert record.actor_kind is PrincipalKind.ANONYMOUS
    assert record.denial is not None and record.denial.code == "authentication_failed"
    assert record.after["kind"] == "session"


def test_flood_in_one_window_is_two_records_at_most() -> None:
    core = build_core()
    auditor = AuthFailureAuditor(core.deps, ApiSettings())
    for _ in range(500):
        auditor.record("10.0.0.1", "service")
    assert len(failures(core)) == 1
    core.clock.advance(timedelta(minutes=2))
    assert auditor.flush() == 1
    records = failures(core)
    assert len(records) == 2
    assert records[-1].after["suppressed"] == 499


def test_window_closing_is_also_detected_by_the_next_failure() -> None:
    core = build_core()
    auditor = AuthFailureAuditor(core.deps, ApiSettings())
    for _ in range(3):
        auditor.record("10.0.0.1", "session")
    core.clock.advance(timedelta(minutes=2))
    auditor.record("10.0.0.1", "session")
    records = failures(core)
    assert [r.after.get("suppressed") for r in records] == [None, 2, None]


def test_different_source_or_kind_has_separate_windows() -> None:
    core = build_core()
    auditor = AuthFailureAuditor(core.deps, ApiSettings())
    auditor.record("10.0.0.1", "session")
    auditor.record("10.0.0.2", "session")
    auditor.record("10.0.0.1", "service")
    assert len(failures(core)) == 3


def test_records_never_contain_credential_values() -> None:
    core = build_core()
    auditor = AuthFailureAuditor(core.deps, ApiSettings())
    auditor.record("10.0.0.1", "malformed")
    text = repr(failures(core))
    assert "ss_" not in text and "st_" not in text and "Bearer" not in text
