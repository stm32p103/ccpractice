"""アプリの骨格: create_app(deps)。

ルーターは /v1 の下に登録する(research.md R3)。ミドルウェアが接続元・本文の上限・request_id・ログを担い、
例外ハンドラーがすべての失敗を problem+json にする。OpenAPI は実装から生成し、`/openapi.json` は認証つきで返す。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI

from .deps import ApiDependencies
from .http.authn import Auth
from .http.handlers import install_handlers
from .http.middleware import BoundaryMiddleware
from .http.openapi import install_openapi
from .http.routers import access, allowlist, audit, auth, events, health, jobs, queue, runner_protocol, runners
from .http.schemas_problem import PROBLEM_RESPONSES
from .http.versioning import API_PREFIX, API_VERSION
from .scheduler import Scheduler
from .settings import ApiSettings

TELEMETRY_DISABLED: Any = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
    "auto_configure": False,
}


def _build(settings: ApiSettings, lifespan: Any = None) -> FastAPI:
    """ルーターと OpenAPI の組み立て(依存を持たない。OpenAPI の書き出しと create_app が共有する)。"""
    app = FastAPI(
        lifespan=lifespan,
        title="Job Platform Core API",
        version=API_VERSION,
        # 既定の公開(/docs・/redoc・/openapi.json)は使わない。/openapi.json は認証つきで登録する
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        # FastAPI の組み込みのテレメトリ(OpenTelemetry)は、環境変数(FASTAPI_OTEL_AUTO_CONFIGURE)で外部へ書き出せる。
        # 検証エラー(入力値を含む)や例外の内容も載りうるため、すべて無効にする(憲章 S1・S2、T-A8、T-A12)。
        telemetry=TELEMETRY_DISABLED,
    )
    install_handlers(app)
    app.include_router(health.router)
    v1 = APIRouter(prefix=API_PREFIX, responses=PROBLEM_RESPONSES)
    v1.include_router(jobs.router)
    v1.include_router(queue.router)
    v1.include_router(runners.router)
    v1.include_router(allowlist.router)
    v1.include_router(audit.router)
    v1.include_router(auth.router)
    v1.include_router(events.router)
    v1.include_router(access.router)
    v1.include_router(runner_protocol.router)
    app.include_router(v1)
    install_openapi(app, cookie_name=settings.cookie_name)
    return app


def openapi_document(settings: ApiSettings | None = None) -> dict[str, Any]:
    """実装から生成した OpenAPI の文書(スナップショットの書き出し・契約の検査用)。"""
    return _build(settings or ApiSettings()).openapi()


def create_app(deps: ApiDependencies, *, run_scheduler: bool = True) -> FastAPI:
    """run_scheduler: アプリの起動・終了に合わせて定期処理を動かす(ワーカーが 1 つである前提。R20)。"""
    scheduler = Scheduler(deps)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if run_scheduler:
            scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()

    app = _build(deps.settings, lifespan)
    app.state.deps = deps
    app.state.scheduler = scheduler
    app.add_middleware(BoundaryMiddleware, settings=deps.settings)

    @app.get("/openapi.json", include_in_schema=False)
    def openapi_json(_auth: Auth) -> dict[str, Any]:
        """この版の OpenAPI(認証が要る。実装から生成する)。"""
        return app.openapi()

    return app
