"""PostgreSQL の試験の環境(`-m postgres`)。接続先の用意は job_testing.pg_fixtures を参照。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from job_core_persistence import make_engine, migrate
from job_core_persistence.models import metadata
from job_testing.pg_fixtures import pg_dsn

__all__ = ["pg_dsn"]


@pytest.fixture(scope="session")
def migrated_dsn(pg_dsn: str) -> str:
    migrate(pg_dsn)
    migrate(pg_dsn)  # 再実行しても変化しない(冪等)
    return pg_dsn


@pytest.fixture
def engine(migrated_dsn: str) -> Iterator[Engine]:
    engine = make_engine(migrated_dsn)
    names = ", ".join(t.name for t in metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(sa.text(f"TRUNCATE {names} RESTART IDENTITY"))
    yield engine
    engine.dispose()
