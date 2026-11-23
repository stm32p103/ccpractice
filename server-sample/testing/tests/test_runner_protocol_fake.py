"""RunnerProtocolContract を FakeRunnerCore に対して実行する(T027)。"""

from __future__ import annotations

import pytest

from job_runner_agent.core_client import CoreClient
from job_runner_agent.secret_source import SecretValue
from job_testing.contracts.runner_protocol import ProtocolEnv, RunnerProtocolContract
from job_testing.runner_fakes.fake_core import FakeRunnerCore


@pytest.fixture
def proto() -> ProtocolEnv:
    core = FakeRunnerCore(lease_seconds=60, heartbeat_interval=30)
    client = CoreClient("http://fake.invalid", SecretValue(core.token), transport=core.transport, allow_insecure=True)
    return ProtocolEnv(
        client=client,
        enqueue=lambda **kw: core.enqueue(**kw),
        request_abort=core.request_abort,
        log_text=core.log_text,
        job_state=lambda job_id: core.jobs[job_id].state,
        capabilities={"k1": "v"},
    )


class TestFakeRunnerCore(RunnerProtocolContract):
    pass
