"""JobRepository.search の契約テストを Fake に対して実行する(quickstart.md V4)。"""

from __future__ import annotations

import pytest

from job_testing.contracts.job_search import JobSearchContract
from job_testing.contracts.persistence import NewUow
from job_testing.core_fakes import InMemoryStore


@pytest.fixture
def new_uow() -> NewUow:
    return InMemoryStore().new_unit_of_work


class TestFakeJobSearch(JobSearchContract):
    pass
