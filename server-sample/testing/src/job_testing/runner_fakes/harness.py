"""エージェントの受け入れ試験の部品(004)。偽のコア・偽のエグゼキュータ・偽のツールでエージェントを動かす。

`AgentHarness` は、一時フォルダの上に、設定(dev)、偽のコア、CoreClient、AgentContext、RunnerAgent を組み立てる。
GitHub・WebUI・本物のコアを使わない(憲章 原則 11)。
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from job_runner_agent.agent import RunnerAgent
from job_runner_agent.artifacts.shared_folder import SharedFolderArtifactStore
from job_runner_agent.core_client import CoreClient
from job_runner_agent.execution import AgentContext
from job_runner_agent.executor import Executor
from job_runner_agent.journal import AgentJournal
from job_runner_agent.launcher.direct import DirectLauncher
from job_runner_agent.launcher.port import ProcessLauncher
from job_runner_agent.secret_source import SecretValue
from job_runner_agent.settings import AgentSettings

from .executors import FakeExecutor
from .fake_core import FakeRunnerCore
from .recording_server import RecordingTransport

SYSTEM_ROOT = os.environ.get("SYSTEMROOT", "C:\\Windows")


def base_settings(tmp: Path, **overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "profile": "dev",
        "core": {"url": "http://fake-core.invalid", "runner_token_secret": "runner-token"},
        "work": {"root": str(tmp / "work"), "min_free_bytes": 0},
        "state": {"dir": str(tmp / "state")},
        "env_allow": {"SystemRoot": SYSTEM_ROOT},
        "tools": {"py": {"path": sys.executable}},
        "executors": {"type-a": {"executor": "fake", "tool_ids": ["py"], "env_names": ["TOOL_MODE"]}},
        "source": {"repository_allowlist": [], "fetcher": "remote"},
        "launcher": {"kind": "direct"},
        "capabilities": {"k1": "v"},
    }
    raw.update(overrides)
    return raw


@dataclass
class AgentHarness:
    tmp: Path
    core: FakeRunnerCore
    settings: AgentSettings
    context: AgentContext
    agent: RunnerAgent
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    recorder: RecordingTransport | None = None
    artifact_dir: Path | None = None

    @classmethod
    def create(
        cls,
        tmp: Path,
        *,
        core: FakeRunnerCore | None = None,
        executors: Mapping[str, Executor] | None = None,
        launcher: ProcessLauncher | None = None,
        poll_interval: float = 0.05,
        settings_overrides: Mapping[str, Any] | None = None,
        timeouts: Mapping[str, Any] | None = None,
        record: bool = True,
        artifact_dir: Path | None = None,
        artifact_limits: Mapping[str, Any] | None = None,
        **context_overrides: Any,
    ) -> AgentHarness:
        fake = core or FakeRunnerCore(lease_seconds=60, heartbeat_interval=0.1)
        overrides = dict(settings_overrides or {})
        if artifact_dir is not None:
            overrides["artifact_store"] = {
                "kind": "shared_folder",
                "shared_folder": {"local_path": str(artifact_dir), "unc_host": "runner-pc", "share_name": "results"},
                **(artifact_limits or {}),
            }
        raw = base_settings(tmp, **overrides)
        settings = AgentSettings.from_mapping(raw)
        settings = dataclasses.replace(settings, poll_interval_seconds=poll_interval)
        if timeouts:
            settings = dataclasses.replace(settings, timeouts=dataclasses.replace(settings.timeouts, **timeouts))
        token = SecretValue(fake.token)
        recorder = RecordingTransport(fake.transport) if record else None
        client = CoreClient(settings.core.url, token, transport=recorder or fake.transport, allow_insecure=True)
        journal = AgentJournal(settings.state.dir, settings.state.audit_retention_days)
        context = AgentContext(
            settings=settings,
            client=client,
            launcher=launcher or DirectLauncher(),
            executors=executors if executors is not None else {"type-a": FakeExecutor()},
            journal=journal,
            secrets=[fake.token],
            artifact_store=SharedFolderArtifactStore(settings.artifact_store) if artifact_dir is not None else None,
        )
        for key, value in context_overrides.items():
            setattr(context, key, value)
        harness = cls(tmp, fake, settings, context, RunnerAgent(context))
        harness.recorder = recorder
        harness.artifact_dir = artifact_dir
        return harness

    @property
    def journal(self) -> AgentJournal:
        return self.context.journal

    def start(self) -> None:
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(self.agent.run(self.stop))

    async def shutdown(self, timeout: float = 20.0) -> None:
        self.stop.set()
        if self.task is not None:
            await asyncio.wait_for(asyncio.gather(self.task, return_exceptions=True), timeout=timeout)
            self.task = None
        await self.context.client.aclose()

    async def wait_for(self, predicate: Callable[[], bool], timeout: float = 20.0, interval: float = 0.02) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.task is not None and self.task.done() and self.task.exception() is not None:
                raise self.task.exception()  # type: ignore[misc]
            if predicate():
                return
            await asyncio.sleep(interval)
        raise TimeoutError("条件が満たされなかった")

    def work_root_entries(self) -> list[Path]:
        root = Path(self.settings.work.root)
        return list(root.iterdir()) if root.exists() else []
