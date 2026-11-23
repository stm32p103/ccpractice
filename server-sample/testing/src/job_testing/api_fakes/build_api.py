"""API のテスト用の組み立て: build_core() + api_fakes + TestClient(quickstart.md §4)。

補助: login_as(subject, groups)(セッションを直接作る)、issue_service_token(permissions)、runner_token()。
GitHub・ランナーの実機・外部のネットワークを使わない。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from job_core.access.permission import Permission
from job_core.access.principal import Principal
from job_core.shared.ids import SubjectId
from job_core_api.access.config import AccessConfig
from job_core_api.access.models import Session
from job_core_api.access.secrets import TokenKind, hash_token, new_token
from job_core_api.app import create_app
from job_core_api.deps import ApiDependencies, CoreUseCases
from job_core_api.settings import ApiSettings

from ..core_fakes import CoreFixture, build_core
from .identity import (
    FakeIdentityProvider,
    InMemoryAccessConfigSource,
    InMemoryServiceCredentialRepository,
    InMemorySessionRepository,
)
from .source_credentials import FakeSourceCredentialIssuer

ALL_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "viewer": ["job.general"],
    "member": ["job.general", "job.submit"],
    "operator": [
        "job.general",
        "job.submit",
        "queue.schedule",
        "job.cancel_queued",
        "job.force_abort",
    ],
    "admin": [
        "job.general",
        "job.submit",
        "queue.schedule",
        "job.cancel_queued",
        "job.force_abort",
        "audit.read_all",
        "runner.manage",
        "access.manage",
    ],
    "reader": ["job.general", "job.read_output"],
}

DEFAULT_ACCESS: dict[str, Any] = {
    "roles": {name: {"permissions": perms} for name, perms in ALL_ROLE_PERMISSIONS.items()},
    "groups": {
        "g-viewer": ["viewer"],
        "g-member": ["member"],
        "g-operator": ["operator"],
        "g-admin": ["admin"],
        "g-reader": ["reader"],
    },
    "default_roles": ["viewer"],
    "service": {
        "permission_ceiling": ["job.submit", "job.general", "job.submit_on_behalf", "queue.schedule"],
    },
}

ADMIN_PRINCIPAL = Principal.of("bootstrap-admin", [Permission.RUNNER_MANAGE, Permission.GENERAL])

REQUIREMENT_K1: dict[str, Any] = {"all": [{"key": "k1", "op": "eq", "value": "v"}]}


def submit_body(**overrides: Any) -> dict[str, Any]:
    """POST /v1/jobs の本文(要件は k1 = v)。definition の項目は definition_* で上書きできる。"""
    definition: dict[str, Any] = {
        "job_type": "t1",
        "requirement": REQUIREMENT_K1,
        "payload": {"n": 1},
        "timeout_seconds": 60,
    }
    for key in list(overrides):
        if key.startswith("definition_"):
            definition[key.removeprefix("definition_")] = overrides.pop(key)
    return {"definition": definition, **overrides}


def use_cases_of(core: CoreFixture) -> CoreUseCases:
    return CoreUseCases.build(core.deps)


@dataclass
class ApiFixture:
    core: CoreFixture
    deps: ApiDependencies
    app: FastAPI
    client: TestClient
    identity: FakeIdentityProvider
    sessions: InMemorySessionRepository
    credentials: InMemoryServiceCredentialRepository
    access_source: InMemoryAccessConfigSource
    source_issuer: FakeSourceCredentialIssuer | None = None
    _counter: int = 0

    def login_as(self, subject: str, groups: Iterable[str] = ()) -> str:
        """セッションを直接作り、値(`ss_...`)を返す。認証基盤・Cookie を通さない。"""
        token = new_token(TokenKind.SESSION)
        now = self.core.clock.now()
        self._counter += 1
        self.sessions.add(
            Session(
                session_id=f"s-test-{self._counter}",
                token_hash=hash_token(token),
                subject_id=SubjectId(subject),
                groups=frozenset(groups),
                created_at=now,
                last_used_at=now,
                expires_at=now + self.deps.settings.session_absolute_timeout,
            )
        )
        return token

    def admin(self, subject: str = "admin") -> str:
        return self.login_as(subject, ["g-admin"])

    def member(self, subject: str = "alice") -> str:
        return self.login_as(subject, ["g-member"])

    def operator(self, subject: str = "op") -> str:
        return self.login_as(subject, ["g-operator"])

    def reader(self, subject: str = "reader") -> str:
        """ログ・成果物の参照の権限(job.read_output)を持つ利用者(004)。"""
        return self.login_as(subject, ["g-reader"])

    def viewer(self, subject: str = "viewer") -> str:
        return self.login_as(subject, ["g-viewer"])

    def issue_service_token(self, permissions: Iterable[str | Permission], name: str | None = None) -> str:
        from job_core_api.access.models import ServiceCredential

        token = new_token(TokenKind.SERVICE)
        now = self.core.clock.now()
        self._counter += 1
        credential_id = f"c-test-{self._counter}"
        self.credentials.add(
            ServiceCredential(
                credential_id=credential_id,
                name=name or f"svc-test-{self._counter}",
                subject_id=SubjectId(f"svc:{credential_id}"),
                permissions=frozenset(Permission(p) for p in permissions),
                token_hash=hash_token(token),
                created_at=now,
                created_by=SubjectId("test"),
            )
        )
        return token

    def runner_token(self, name: str = "r-a") -> tuple[str, str]:
        """ランナーを作り、(runner_id, 値 `rt_...`) を返す(002 のユースケースを直接呼ぶ)。"""
        created = self.core.create_runner(ADMIN_PRINCIPAL, name=name)
        return str(created.runner_id), created.token.value

    def register_runner(self, name: str = "r-a", capabilities: dict[str, Any] | None = None) -> tuple[str, str]:
        """許可リストに能力のキーを足し、ランナーを作って登録する。(runner_id, 値 `rt_...`) を返す。"""
        caps = capabilities if capabilities is not None else {"k1": "v"}
        entries = {str(k): kind.value for k, kind in self.core.get_allowlist(ADMIN_PRINCIPAL).entries.items()}
        for key, value in caps.items():
            entries[key] = "set" if isinstance(value, list) else "single"
        self.core.replace_allowlist(ADMIN_PRINCIPAL, entries=entries)
        runner_id, token = self.runner_token(name)
        self.core.register_runner(self.core.authenticate_runner(token), runner_id=runner_id, capabilities=caps)
        return runner_id, token

    def assign_next(self, runner_id: str, token: str) -> str | None:
        """ランナーとして割り当てを要求し(コアを直接呼ぶ)、割り当てられたジョブの識別子を返す。"""
        result = self.core.request_job(self.core.authenticate_runner(token), runner_id=runner_id)
        return str(result.assignment.job_id) if result.assignment else None

    def queue_order(self) -> list[str]:
        """待機列の順序(コアを直接呼ぶ)。"""
        view = self.core.list_jobs(ADMIN_PRINCIPAL, states=["queued"])
        return [str(item.job_id) for item in view.queued]

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def advance(self, delta: timedelta) -> None:
        self.core.clock.advance(delta)


def build_api(
    *,
    settings: ApiSettings | None = None,
    access: dict[str, Any] | None = None,
    use_runner_management: bool = True,
    raise_server_exceptions: bool = False,
    with_source_issuer: bool = True,
) -> ApiFixture:
    core = build_core(use_runner_management=use_runner_management)
    identity = FakeIdentityProvider()
    sessions = InMemorySessionRepository()
    credentials = InMemoryServiceCredentialRepository()
    config = AccessConfig.from_mapping(access or DEFAULT_ACCESS)
    access_source = InMemoryAccessConfigSource(config)
    issuer = FakeSourceCredentialIssuer(core.clock.now) if with_source_issuer else None
    deps = ApiDependencies.assemble(
        core=use_cases_of(core),
        settings=settings or ApiSettings(),
        identity=identity,
        sessions=sessions,
        credentials=credentials,
        access_source=access_source,
        source_credentials=issuer,
    )
    app = create_app(deps)
    client = TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=raise_server_exceptions)
    return ApiFixture(
        core=core,
        deps=deps,
        app=app,
        client=client,
        identity=identity,
        sessions=sessions,
        credentials=credentials,
        access_source=access_source,
        source_issuer=issuer,
    )
