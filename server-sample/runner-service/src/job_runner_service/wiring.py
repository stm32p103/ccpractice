"""組み立て(research.md R1)。

エグゼキュータの実装は、**コード内の対応表**(名前 → 実装)から選ぶ。動的なプラグイン読み込み(文字列からの import)
は使わない。
新しい用途のエグゼキュータの追加は、この対応表に 1 行足し、設定の `executors` で対応付けるだけ(
エージェントの中核は変えない)。
ポートの実装(SecretSource、ProcessLauncher、SourceFetcher、ArtifactStore)は、設定の profile と種類で選ぶ。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from job_profile_equipment_check.executor import EquipmentCheckExecutor
from job_runner_agent.artifacts.port import ArtifactStore
from job_runner_agent.artifacts.shared_folder import SharedFolderArtifactStore
from job_runner_agent.core_client import CoreClient
from job_runner_agent.execution import AgentContext
from job_runner_agent.executor import Executor
from job_runner_agent.journal import AgentJournal
from job_runner_agent.launcher.direct import DirectLauncher
from job_runner_agent.launcher.port import ProcessLauncher
from job_runner_agent.secret_source import CredentialStoreSecretSource, EnvSecretSource, SecretSource
from job_runner_agent.settings import AgentSettings
from job_runner_agent.source import LocalDirectorySourceFetcher, SourceFetcher

ExecutorFactory = Callable[[], Executor]

# エグゼキュータの対応表(コード内)。キーは設定の `executors.<job_type>.executor` で使う名前。
EXECUTOR_TABLE: Mapping[str, ExecutorFactory] = {
    "equipment-check": EquipmentCheckExecutor,
}


class WiringError(ValueError):
    """設定がコードの対応表・実装の選択肢に合わない。メッセージに値を含めない。"""


def build_executors(
    settings: AgentSettings, table: Mapping[str, ExecutorFactory] = EXECUTOR_TABLE
) -> dict[str, Executor]:
    """設定の job_type ごとに、対応表のエグゼキュータを 1 つ作る。未知の名前は起動を拒否する。"""
    executors: dict[str, Executor] = {}
    for job_type, binding in settings.executors.items():
        factory = table.get(binding.executor)
        if factory is None:
            raise WiringError(f"executors.{job_type}.executor: 未知のエグゼキュータ")
        executors[job_type] = factory()
    return executors


def build_secret_source(settings: AgentSettings) -> SecretSource:
    return EnvSecretSource() if settings.is_dev else CredentialStoreSecretSource()


def build_launcher(settings: AgentSettings, secrets: SecretSource) -> ProcessLauncher:
    if settings.launcher.kind == "direct":
        if not settings.is_dev:
            raise WiringError("launcher.kind: direct は dev のみ")
        return DirectLauncher()
    from job_runner_agent.launcher.logon import LogonLauncher

    return LogonLauncher(secrets, settings.launcher.tool_account_secret or "")


def build_fetcher(settings: AgentSettings) -> SourceFetcher | None:
    if settings.source.fetcher == "local_directory":
        if not settings.is_dev:
            raise WiringError("source.fetcher: local_directory は dev のみ")
        return LocalDirectorySourceFetcher(settings.source.local_directory_root or "")
    return None  # remote の実アダプタは 005。構成されていなければ、取得を要するジョブは source_unavailable で失敗する


def build_artifact_store(settings: AgentSettings) -> ArtifactStore | None:
    kind = settings.artifact_store.kind
    if kind == "disabled":
        return None
    if kind == "shared_folder":
        return SharedFolderArtifactStore(settings.artifact_store)
    raise WiringError("artifact_store.kind: https_storage の実装は保存先の確定後に追加する")


def build_context(
    settings: AgentSettings,
    *,
    table: Mapping[str, ExecutorFactory] = EXECUTOR_TABLE,
    secrets: SecretSource | None = None,
    launcher: ProcessLauncher | None = None,
    fetcher: SourceFetcher | None = None,
) -> AgentContext:
    secret_source = secrets or build_secret_source(settings)
    token = secret_source.get(settings.core.runner_token_secret)
    client = CoreClient(
        settings.core.url,
        token,
        verify=settings.core.ca_bundle or True,
        allow_insecure=settings.is_dev,
    )
    return AgentContext(
        settings=settings,
        client=client,
        launcher=launcher or build_launcher(settings, secret_source),
        executors=build_executors(settings, table),
        journal=AgentJournal(settings.state.dir, settings.state.audit_retention_days),
        secrets=[token.reveal()],
        fetcher=fetcher if fetcher is not None else build_fetcher(settings),
        artifact_store=build_artifact_store(settings),
    )
