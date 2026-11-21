"""runner のポートの契約テストを Fake に対して実行する(quickstart.md V4)。"""

from __future__ import annotations

import pytest

from job_core.runner.application.ports import RunnerCatalog
from job_testing.contracts.runner_persistence import (
    CapabilityAllowlistRepositoryContract,
    LeaseRepositoryContract,
    NewRunnerUow,
    RunnerCatalogContract,
    RunnerRepositoryContract,
    RunnerTokenRepositoryContract,
    RunnerUnitOfWorkContract,
)
from job_testing.core_fakes import InMemoryRunnerCatalog, InMemoryStore


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def new_uow(store: InMemoryStore) -> NewRunnerUow:
    return store.new_unit_of_work


@pytest.fixture
def catalog(store: InMemoryStore) -> RunnerCatalog:
    return InMemoryRunnerCatalog(store.runner_state, store.lock)


class TestFakeRunnerUnitOfWork(RunnerUnitOfWorkContract):
    pass


class TestFakeRunnerRepository(RunnerRepositoryContract):
    pass


class TestFakeLeaseRepository(LeaseRepositoryContract):
    pass


class TestFakeRunnerTokenRepository(RunnerTokenRepositoryContract):
    pass


class TestFakeCapabilityAllowlistRepository(CapabilityAllowlistRepositoryContract):
    pass


class TestFakeRunnerCatalog(RunnerCatalogContract):
    pass
