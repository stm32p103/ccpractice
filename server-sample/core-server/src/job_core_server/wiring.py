"""組み立て(composition root。憲章 原則 3)。ポートの実装を選び、`create_app` に渡す。

`profile = "dev"` のメモリ構成だけが、試験用の実装(Fake の認証基盤・メモリ上のリポジトリ)を使う。これらは
`job_testing` にあり、dev のときだけ import する(本番の構成では import されない)。
外部の認証基盤のアダプタ(005)と PostgreSQL の永続化(`job_core_persistence`)は、設定で選べるようになったとき接続する。
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import FastAPI

from job_core.job.application.ports import UnitOfWorkFactory
from job_core.runner.application import RunnerDependencies, RunnerEligibilityService, RunnerTimingPolicy
from job_core.runner.application.ports import RunnerCatalog
from job_core.shared.secret_generator import SystemSecretGenerator
from job_core_api.access.config_file import TomlAccessConfigSource
from job_core_api.access.ports import ServiceCredentialRepository, SessionRepository
from job_core_api.app import create_app
from job_core_api.deps import ApiDependencies, CoreUseCases
from job_core_api.secret_source import SecretNotFound, SecretSource
from job_core_api.settings import DEFAULT_ALLOWED_NETWORKS, ApiSettings

from .adapters import SystemClock, UuidIdGenerator
from .secret_source_env import EnvSecretSource
from .settings import ConfigError, ServerSettings

logger = logging.getLogger("job_core_server")


def api_settings_of(settings: ServerSettings) -> ApiSettings:
    return ApiSettings(
        allowed_networks=settings.allowed_networks or DEFAULT_ALLOWED_NETWORKS,
        cookie_secure=settings.cookie_secure,
        allowed_origins=settings.allowed_origins,
        session_retention=timedelta(days=7),
    )


def build_app(settings: ServerSettings, secrets: SecretSource | None = None) -> FastAPI:
    """設定から、API のアプリを組み立てる。設定の検査(profile の保護)は、設定の読み込みで済んでいる。

    永続化は設定で選ぶ(memory は dev だけ。postgres は接続の秘密を SecretSource から取得する)。
    外部の認証基盤のアダプタ(005)は未接続のため、`identity.provider = "external"` では
    起動を拒否する(Fake へ黙って切り替えない)。
    """
    for warning in settings.warnings:
        logger.warning(warning)
    if settings.identity_provider != "fake":
        raise ConfigError([("identity.provider", "外部の認証基盤のアダプタ(005)は未接続")])
    if not settings.is_dev:  # 防御(設定の検査で拒否済み)
        raise ConfigError([("profile", "Fake の認証基盤は dev でだけ使える")])

    from job_testing.api_fakes import FakeIdentityProvider

    clock, ids = SystemClock(), UuidIdGenerator()
    if settings.persistence_kind == "memory":
        from job_testing.api_fakes import (
            InMemoryServiceCredentialRepository,
            InMemorySessionRepository,
        )
        from job_testing.core_fakes import InMemoryRunnerCatalog, InMemoryStore

        store = InMemoryStore()
        catalog: RunnerCatalog = InMemoryRunnerCatalog(store.runner_state, store.lock)
        uow_factory: UnitOfWorkFactory = store.new_unit_of_work
        sessions: SessionRepository = InMemorySessionRepository()
        credentials: ServiceCredentialRepository = InMemoryServiceCredentialRepository()
    else:
        from job_core_persistence import (
            SqlRunnerCatalog,
            SqlServiceCredentialRepository,
            SqlSessionRepository,
            make_engine,
            migrate,
            sql_uow_factory,
        )

        source = secrets or EnvSecretSource()
        try:
            dsn = source.get(settings.database_secret or "")
        except SecretNotFound:
            raise ConfigError([("persistence.dsn_secret", "接続の秘密を取得できない")]) from None
        migrate(dsn)  # 開発では、起動時に最新へ適用する(本番は 009 の migrate.ps1)
        engine = make_engine(dsn)
        catalog = SqlRunnerCatalog(engine)
        uow_factory = sql_uow_factory(engine)
        sessions = SqlSessionRepository(engine)
        credentials = SqlServiceCredentialRepository(engine)

    deps = RunnerDependencies(
        uow_factory=uow_factory,
        eligibility=RunnerEligibilityService(catalog),
        clock=clock,
        ids=ids,
        max_conflict_retries=3,
        catalog=catalog,
        secrets=SystemSecretGenerator(),
        timing=RunnerTimingPolicy(),
    )
    api_deps = ApiDependencies.assemble(
        core=CoreUseCases.build(deps),
        settings=api_settings_of(settings),
        identity=FakeIdentityProvider(),
        sessions=sessions,
        credentials=credentials,
        access_source=TomlAccessConfigSource(settings.access_config_path),
    )
    return create_app(api_deps)
