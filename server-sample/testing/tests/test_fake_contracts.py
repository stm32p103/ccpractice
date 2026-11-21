"""ポートの契約テストを Fake に対して実行する(quickstart.md V4)。"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from job_core.job.domain.values import RunnerRequirement
from job_testing.contracts.audit_outbox import AuditLogContract, OutboxContract
from job_testing.contracts.persistence import (
    JobRepositoryContract,
    NewUow,
    QueueRepositoryContract,
    UnitOfWorkContract,
)
from job_testing.contracts.runner_eligibility import EligibilityEnv, RunnerEligibilityContract
from job_testing.core_fakes import FakeRunnerEligibility, InMemoryStore


@pytest.fixture
def new_uow() -> NewUow:
    return InMemoryStore().new_unit_of_work


@pytest.fixture
def eligibility_env() -> EligibilityEnv:
    fake = FakeRunnerEligibility()

    def register(runner_id: str, capabilities: Mapping[str, object]) -> None:
        fake.register(runner_id, capabilities)

    return EligibilityEnv(
        eligibility=fake,
        register=register,
        unregister=fake.unregister,
        requirement_for=lambda caps: RunnerRequirement.of(dict(caps)),
    )


class TestFakeUnitOfWork(UnitOfWorkContract):
    pass


class TestFakeJobRepository(JobRepositoryContract):
    pass


class TestFakeQueueRepository(QueueRepositoryContract):
    pass


class TestFakeAuditLog(AuditLogContract):
    pass


class TestFakeOutbox(OutboxContract):
    pass


class TestFakeRunnerEligibility(RunnerEligibilityContract):
    pass
