"""JobLogStore の契約テストを Fake に対して実行する(004 T010)。"""

from __future__ import annotations

import pytest

from job_core.job.application.ports import JobLogStore
from job_testing.contracts.job_log import JobLogStoreContract
from job_testing.core_fakes import InMemoryJobLogStore


@pytest.fixture
def log_store() -> JobLogStore:
    return InMemoryJobLogStore()


class TestFakeJobLogStore(JobLogStoreContract):
    pass
