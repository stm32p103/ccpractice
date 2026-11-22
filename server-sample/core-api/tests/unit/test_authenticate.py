"""認証(research.md R4、T-A2)。3 種の主体、失効の即時性、対応表の変更、失敗の区別がないこと。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal, PrincipalKind
from job_core.shared.ids import SubjectId
from job_core_api.access.audit import AuthFailureAuditor
from job_core_api.access.authenticate import AuthenticationFailed, Authenticator
from job_core_api.access.config import AccessConfig
from job_core_api.access.holder import AccessConfigHolder
from job_core_api.access.secrets import TokenKind, hash_token, new_token
from job_core_api.settings import ApiSettings
from job_testing.api_fakes import InMemoryServiceCredentialRepository, InMemorySessionRepository
from job_testing.contracts.access_config import VALID, variant
from job_testing.contracts.service_credentials import make_credential, make_session
from job_testing.core_fakes import CoreFixture, build_core

ADMIN = Principal.of("admin", [P.RUNNER_MANAGE])


class Env:
    def __init__(self, config: dict | None = None) -> None:  # type: ignore[type-arg]
        self.core: CoreFixture = build_core(use_runner_management=True)
        self.sessions = InMemorySessionRepository()
        self.credentials = InMemoryServiceCredentialRepository()
        self.holder = AccessConfigHolder(AccessConfig.from_mapping(config or VALID))
        self.settings = ApiSettings()
        self.auditor = AuthFailureAuditor(self.core.deps, self.settings)
        self.authenticator = Authenticator(
            deps=self.core.deps,
            settings=self.settings,
            sessions=self.sessions,
            credentials=self.credentials,
            access=self.holder,
            authenticate_runner=self.core.authenticate_runner,
            auditor=self.auditor,
        )

    def add_session(self, groups: frozenset[str] = frozenset({"g-members"}), subject: str = "u1") -> str:
        token = new_token(TokenKind.SESSION)
        now = self.core.clock.now()
        self.sessions.add(
            make_session(
                f"s-{subject}",
                subject,
                token_hash=hash_token(token),
                groups=groups,
                created_at=now,
                last_used_at=now,
                expires_at=now + timedelta(hours=12),
            )
        )
        return token

    def add_service(self, permissions: frozenset[P], name: str = "svc") -> str:
        token = new_token(TokenKind.SERVICE)
        self.credentials.add(make_credential(f"c-{name}", name, token_hash=hash_token(token), permissions=permissions))
        return token


def test_three_kinds_of_principals_are_authenticated() -> None:
    env = Env()
    human = env.authenticator.authenticate(env.add_session(), source="10.0.0.1")
    assert human.principal.kind is PrincipalKind.HUMAN
    assert human.principal.permissions == {P.GENERAL, P.JOB_SUBMIT}
    assert human.session is not None

    service = env.authenticator.authenticate(env.add_service(frozenset({P.JOB_SUBMIT})), source="10.0.0.1")
    assert service.principal.kind is PrincipalKind.SERVICE
    assert service.principal.permissions == {P.JOB_SUBMIT}

    created = env.core.create_runner(ADMIN, name="r-a")
    runner = env.authenticator.authenticate(created.token.value, source="10.0.0.1")
    assert runner.principal.kind is PrincipalKind.RUNNER
    assert runner.principal.permissions == {P.RUNNER_REPORT, P.JOB_EXECUTE}


@pytest.mark.parametrize("value", [None, "", "garbage", "xx_abc", "ss_unknown", "st_unknown", "rt_unknown"])
def test_unknown_or_malformed_values_fail_without_distinction(value: str | None) -> None:
    env = Env()
    with pytest.raises(AuthenticationFailed) as info:
        env.authenticator.authenticate(value, source="10.0.0.1")
    assert str(info.value) == ""


def test_revocation_takes_effect_on_the_next_call() -> None:
    env = Env()
    session_token = env.add_session()
    service_token = env.add_service(frozenset({P.JOB_SUBMIT}))
    runner = env.core.create_runner(ADMIN, name="r-a")
    for token in (session_token, service_token, runner.token.value):
        env.authenticator.authenticate(token, source="s")
    now = env.core.clock.now()
    env.sessions.revoke("s-u1", now)
    env.credentials.save(env.credentials.get("c-svc").revoke(now))  # type: ignore[union-attr]
    env.core.revoke_token(ADMIN, runner_id=runner.runner_id)
    for token in (session_token, service_token, runner.token.value):
        with pytest.raises(AuthenticationFailed):
            env.authenticator.authenticate(token, source="s")


def test_session_expires_by_idle_and_absolute_timeouts() -> None:
    env = Env()
    token = env.add_session()
    env.core.clock.advance(timedelta(hours=2, minutes=1))
    with pytest.raises(AuthenticationFailed):
        env.authenticator.authenticate(token, source="s")
    token2 = env.add_session(subject="u2")
    for _ in range(9):  # 1.5 時間ごとに使い続けても、絶対期限(12 時間)で失効する
        env.core.clock.advance(timedelta(hours=1, minutes=30))
        try:
            env.authenticator.authenticate(token2, source="s")
        except AuthenticationFailed:
            break
    else:
        pytest.fail("絶対期限で失効しなかった")


def test_access_config_change_applies_from_the_next_call_without_relogin() -> None:
    env = Env()
    token = env.add_session()
    assert env.authenticator.authenticate(token, source="s").principal.permissions == {P.GENERAL, P.JOB_SUBMIT}
    env.holder.replace(AccessConfig.from_mapping(variant(groups={"g-members": ["viewer"]})))
    assert env.authenticator.authenticate(token, source="s").principal.permissions == {P.GENERAL}


def test_service_permissions_are_capped_by_the_current_ceiling() -> None:
    env = Env()
    token = env.add_service(frozenset({P.JOB_SUBMIT, P.QUEUE_SCHEDULE}))
    # VALID の上限は job.submit・job.general・job.submit_on_behalf。queue.schedule は上限の外
    assert env.authenticator.authenticate(token, source="s").principal.permissions == {P.JOB_SUBMIT}


def test_failures_are_audited_and_suppressed() -> None:
    env = Env()
    for _ in range(20):
        with pytest.raises(AuthenticationFailed):
            env.authenticator.authenticate("ss_nope", source="10.0.0.9")
    from job_core.job.application import AuditFilter, AuditOperation

    with env.core.new_uow() as uow:
        page = uow.audit.query(AuditFilter(operation=AuditOperation.AUTH_FAILED), None, 100)
    assert len(page.items) == 1
    assert "ss_nope" not in repr(page.items)


def test_principal_subject_for_service_comes_from_the_credential() -> None:
    env = Env()
    token = env.add_service(frozenset({P.JOB_SUBMIT}))
    assert env.authenticator.authenticate(token, source="s").principal.subject_id == SubjectId("svc:c-svc")
