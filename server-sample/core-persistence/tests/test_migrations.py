"""マイグレーション(Alembic)が、空の DB から最新に適用でき、再実行しても変化しないこと(quickstart V26)。"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from job_core_persistence import make_engine, migrate
from job_core_persistence.models import metadata

pytestmark = pytest.mark.postgres


def test_a_fresh_database_is_migrated_to_head_and_rerun_is_a_no_op(pg_dsn: str) -> None:
    admin = make_engine(pg_dsn)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(sa.text("DROP DATABASE IF EXISTS migration_probe"))
        conn.execute(sa.text("CREATE DATABASE migration_probe"))
    url = make_url(pg_dsn).set(database="migration_probe").render_as_string(hide_password=False)
    migrate(url)
    migrate(url)  # 冪等
    probe = make_engine(url)
    try:
        with probe.connect() as conn:
            tables = {
                row[0] for row in conn.execute(sa.text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
            }
            version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
        assert {t.name for t in metadata.sorted_tables} <= tables
        assert version == "0001"
    finally:
        probe.dispose()
        admin.dispose()


def test_secrets_and_token_values_have_no_column() -> None:
    columns = {c.name for t in metadata.sorted_tables for c in t.columns}
    assert not {"token", "password", "secret", "token_value"} & columns
