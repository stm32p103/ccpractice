"""core-api のポートの契約テストを Fake に対して実行する(quickstart.md V4)。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from job_core_api.access.config import AccessConfig
from job_core_api.access.ports import AccessConfigSource, ServiceCredentialRepository, SessionRepository
from job_testing.api_fakes import (
    FakeIdentityProvider,
    InMemoryAccessConfigSource,
    InMemoryServiceCredentialRepository,
    InMemorySessionRepository,
)
from job_testing.contracts.access_config import AccessConfigContract, ConfigEnv
from job_testing.contracts.identity_provider import IdentityEnv, IdentityProviderContract
from job_testing.contracts.service_credentials import ServiceCredentialContract, SessionContract


class TestFakeIdentityProvider(IdentityProviderContract):
    @pytest.fixture
    def identity_env(self) -> IdentityEnv:
        provider = FakeIdentityProvider()
        provider.accept_unregistered = False
        provider.register("u1", {"g1"})

        def set_available(value: bool) -> None:
            provider.available = value

        return IdentityEnv(
            provider=provider,
            valid_proof={"subject": "u1"},
            invalid_proof={"subject": "stranger-with-a-secret-value"},
            expected_subject="u1",
            set_available=set_available,
        )


class TestInMemoryServiceCredentials(ServiceCredentialContract):
    @pytest.fixture
    def credentials(self) -> ServiceCredentialRepository:
        return InMemoryServiceCredentialRepository()


class TestInMemorySessions(SessionContract):
    @pytest.fixture
    def sessions(self) -> SessionRepository:
        return InMemorySessionRepository()


class TestInMemoryAccessConfig(AccessConfigContract):
    @pytest.fixture
    def config_env(self) -> ConfigEnv:
        holder: dict[str, Mapping[str, Any]] = {}

        def supplier() -> AccessConfig:
            return AccessConfig.from_mapping(holder["data"])

        source: AccessConfigSource = InMemoryAccessConfigSource(supplier)

        def set_config(data: Mapping[str, Any]) -> None:
            holder["data"] = data

        return ConfigEnv(source=source, set_config=set_config)
