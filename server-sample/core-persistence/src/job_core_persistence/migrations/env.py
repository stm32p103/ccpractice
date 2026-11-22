"""Alembic の環境(オンラインのマイグレーションだけ。接続の文字列は設定から受け取る)。"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from job_core_persistence.models import metadata

config = context.config

engine = create_engine(config.get_main_option("sqlalchemy.url") or "", poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
