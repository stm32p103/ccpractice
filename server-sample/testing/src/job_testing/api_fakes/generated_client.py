"""生成クライアントの補助(SC-001)。

アプリの OpenAPI から `openapi-python-client` でクライアントを一時ディレクトリに生成し、
アプリ(TestClient)につなぐ。生成クライアントは httpx2 を使うため、TestClient(httpx)への橋渡しの
トランスポートを使う。
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx2
from fastapi.testclient import TestClient

PACKAGE = "job_api_client"


def generate_client_package(openapi: dict[str, Any], target_dir: Path) -> ModuleType:
    """OpenAPI からクライアントを生成して import する。"""
    spec = target_dir / "openapi.json"
    spec.write_text(json.dumps(openapi, ensure_ascii=False), encoding="utf-8")
    output = target_dir / PACKAGE
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "openapi_python_client",
            "generate",
            "--path",
            str(spec),
            "--output-path",
            str(output),
            "--meta",
            "none",
            "--overwrite",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Warning" not in result.stdout and "error" not in result.stdout.lower(), result.stdout
    sys.path.insert(0, str(target_dir))
    importlib.invalidate_caches()
    return importlib.import_module(PACKAGE)


class BridgeTransport(httpx2.BaseTransport):
    """httpx2 の要求を、アプリの TestClient(httpx)へ橋渡しする。"""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        response = self._client.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.read()
        )
        skipped = {"content-encoding", "transfer-encoding", "content-length"}
        headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in skipped]
        return httpx2.Response(response.status_code, headers=headers, content=response.content)


def client_for(package: ModuleType, test_client: TestClient, token: str | None = None) -> Any:
    """生成クライアント(認証つき。token が None なら認証なし)をアプリにつなぐ。"""
    transport = BridgeTransport(test_client)
    client_module = importlib.import_module(f"{PACKAGE}.client")
    if token is None:
        return client_module.Client(base_url="http://testserver", httpx_args={"transport": transport})
    return client_module.AuthenticatedClient(
        base_url="http://testserver", token=token, httpx_args={"transport": transport}
    )
