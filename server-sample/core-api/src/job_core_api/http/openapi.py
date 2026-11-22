"""OpenAPI の生成(research.md R3)。実装(ルーター・モデル)から生成し、手で書き換えない。

FastAPI が生成した文書に、次を加える: エラー応答の媒体(application/problem+json)、認証の方式と各操作の要否、
情報(版)。認証が要らない操作は NO_AUTH_OPERATIONS に列挙する。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

NO_AUTH_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("get", "/healthz"),
        ("get", "/v1/auth/login"),
        ("get", "/v1/auth/callback"),
        ("post", "/v1/auth/login"),
    }
)

DESCRIPTION = (
    "コアのジョブ受付・キュー管理・ランナー管理を HTTP で公開する API(版 1)。"
    "未知の項目・列挙値は無視すること(互換を保つ追加のため)。エラーは application/problem+json。"
)


def build_openapi(app: FastAPI, *, cookie_name: str) -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=DESCRIPTION, routes=app.routes)
    components = schema.setdefault("components", {})
    components["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "description": "ss_(セッション)・st_(サービス)・rt_(ランナー)",
        },
        "cookieAuth": {"type": "apiKey", "in": "cookie", "name": cookie_name},
    }
    for path, item in schema.get("paths", {}).items():
        for method, operation in item.items():
            if method not in {"get", "put", "post", "delete", "patch"}:
                continue
            if (method, path) not in NO_AUTH_OPERATIONS:
                operation["security"] = [{"bearerAuth": []}, {"cookieAuth": []}]
            for status, response in operation.get("responses", {}).items():
                if status.isdigit() and int(status) >= 400:
                    content = response.get("content", {})
                    if "application/json" in content:
                        content["application/problem+json"] = content.pop("application/json")
    app.openapi_schema = schema
    return schema


def install_openapi(app: FastAPI, *, cookie_name: str) -> None:
    app.openapi = lambda: build_openapi(app, cookie_name=cookie_name)  # type: ignore[method-assign]
