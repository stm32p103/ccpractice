"""エンジンの生成とマイグレーションの適用。接続の文字列(秘密を含む)は、ログ・例外に出さない。"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def normalize_dsn(dsn: str) -> str:
    """`postgresql://...` を、psycopg(3)のドライバーを指す形にする。"""
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn.removeprefix(prefix)
    return dsn


def make_engine(dsn: str, *, pool_size: int = 10) -> Engine:
    return create_engine(normalize_dsn(dsn), pool_size=pool_size, max_overflow=10, pool_pre_ping=True)


def migrate(dsn: str, revision: str = "head") -> None:
    """マイグレーションを適用する。空の DB から最新まで適用でき、再実行しても変化しない(冪等)。"""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", normalize_dsn(dsn).replace("%", "%%"))
    command.upgrade(config, revision)
