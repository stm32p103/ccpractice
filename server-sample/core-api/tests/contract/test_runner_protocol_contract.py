"""RunnerProtocolContract を、本物のコア API(build_api())に対して実行する(T027)。FakeRunnerCore
と同じ結果になること。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from job_runner_agent.core_client import CoreClient
from job_runner_agent.secret_source import SecretValue
from job_testing.api_fakes import ApiFixture, build_api, submit_body
from job_testing.contracts.runner_protocol import ProtocolEnv, RunnerProtocolContract

H = ApiFixture.headers


@pytest.fixture
def proto() -> ProtocolEnv:
    api = build_api()
    _, token = api.register_runner("r-a", {"k1": "v"})
    alice, operator, reader = api.member("alice"), api.operator("op"), api.reader()

    def enqueue(source: str | None = None, revision: str | None = None, **_: Any) -> str:
        body = submit_body()
        if source is not None:
            body["definition"]["source"] = source
            if revision is not None:
                body["definition"]["revision"] = revision
        response = api.client.post("/v1/jobs", json=body, headers=H(alice))
        assert response.status_code == 201, response.text
        return str(response.json()["job_id"])

    def request_abort(job_id: str) -> None:
        assert (
            api.client.post(f"/v1/jobs/{job_id}/cancel", json={"reason": "stop"}, headers=H(operator)).status_code
            == 200
        )

    def log_text(job_id: str) -> str:
        page = api.client.get(f"/v1/jobs/{job_id}/logs", headers=H(reader))
        assert page.status_code == 200, page.text
        return "".join(chunk["text"] for chunk in page.json()["chunks"])

    def job_state(job_id: str) -> str:
        return str(api.client.get(f"/v1/jobs/{job_id}", headers=H(alice)).json()["summary"]["state"])

    client = CoreClient(
        "http://testserver",
        SecretValue(token),
        transport=httpx.ASGITransport(app=api.app, client=("127.0.0.1", 50000)),
        allow_insecure=True,
    )
    return ProtocolEnv(client, enqueue, request_abort, log_text, job_state, {"k1": "v"})


class TestCoreApi(RunnerProtocolContract):
    pass
