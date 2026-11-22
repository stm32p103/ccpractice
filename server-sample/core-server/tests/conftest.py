"""core-server の試験の環境。PostgreSQL の接続先(`pg_dsn`)は job_testing.pg_fixtures を参照。"""

from __future__ import annotations

from job_testing.pg_fixtures import pg_dsn

__all__ = ["pg_dsn"]
