"""001・002・003 のポートの契約テストを、PostgreSQL(SQLAlchemy)に対して実行する(quickstart V26)。

Fake に対して実行するのと同じ契約テストのクラスを継承する(憲章 原則 11)。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy import Engine

from job_core.job.domain.values import RunnerRequirement
from job_core_api.access.ports import ServiceCredentialRepository, SessionRepository
from job_core_persistence import (
    SqlRunnerCatalog,
    SqlServiceCredentialRepository,
    SqlSessionRepository,
    sql_uow_factory,
)
from job_testing.contracts.audit_outbox import AuditLogContract, OutboxContract
from job_testing.contracts.job_search import JobSearchContract
from job_testing.contracts.persistence import (
    JobRepositoryContract,
    NewUow,
    QueueRepositoryContract,
    UnitOfWorkContract,
)
from job_testing.contracts.runner_persistence import (
    CapabilityAllowlistRepositoryContract,
    LeaseRepositoryContract,
    NewRunnerUow,
    RunnerCatalogContract,
    RunnerRepositoryContract,
    RunnerTokenRepositoryContract,
    RunnerUnitOfWorkContract,
)
from job_testing.contracts.service_credentials import ServiceCredentialContract, SessionContract

pytestmark = pytest.mark.postgres


@pytest.fixture
def new_uow(engine: Engine) -> NewUow:
    return sql_uow_factory(engine)  # type: ignore[return-value]


@pytest.fixture
def catalog(engine: Engine) -> SqlRunnerCatalog:
    return SqlRunnerCatalog(engine)


@pytest.fixture
def credentials(engine: Engine) -> ServiceCredentialRepository:
    return SqlServiceCredentialRepository(engine)


@pytest.fixture
def sessions(engine: Engine) -> SessionRepository:
    return SqlSessionRepository(engine)


class TestSqlUnitOfWork(UnitOfWorkContract):
    pass


class TestSqlJobRepository(JobRepositoryContract):
    pass


class TestSqlQueueRepository(QueueRepositoryContract):
    pass


class TestSqlAuditLog(AuditLogContract):
    pass


class TestSqlOutbox(OutboxContract):
    pass


class TestSqlJobSearch(JobSearchContract):
    pass


class TestSqlRunnerUnitOfWork(RunnerUnitOfWorkContract):
    pass


class TestSqlRunnerRepository(RunnerRepositoryContract):
    pass


class TestSqlLeaseRepository(LeaseRepositoryContract):
    pass


class TestSqlRunnerTokenRepository(RunnerTokenRepositoryContract):
    pass


class TestSqlCapabilityAllowlistRepository(CapabilityAllowlistRepositoryContract):
    pass


class TestSqlRunnerCatalog(RunnerCatalogContract):
    pass


class TestSqlServiceCredentials(ServiceCredentialContract):
    pass


class TestSqlSessions(SessionContract):
    pass


_UNUSED: tuple[Any, ...] = (Mapping, NewRunnerUow, RunnerRequirement)
