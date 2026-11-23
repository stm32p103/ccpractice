"""エージェントの設定(data-model.md §1.1。contracts/agent-config.schema.json)。

値オブジェクトとして不変。読み込み(TOML → 辞書)は runner-service が行い、ここでは検証だけを行う。
既定は拒否: 許可リストは空、artifact_store は disabled。`profile != "dev"` では dev 用の選択肢を拒否する。
秘密の値は持たない(資格情報の名前だけ)。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FORBIDDEN_TOOL_SUFFIXES = (".bat", ".cmd")


class SettingsError(ValueError):
    """設定が検証に通らない。違反は場所と理由だけ(値の抜粋を含めない)。"""

    def __init__(self, violations: list[tuple[str, str]]) -> None:
        super().__init__("; ".join(f"{where}: {why}" for where, why in violations))
        self.violations = violations


@dataclass(frozen=True)
class CoreSettings:
    url: str
    runner_token_secret: str
    ca_bundle: str | None = None


@dataclass(frozen=True)
class WorkSettings:
    root: str
    min_free_bytes: int = 10 * 1024**3


@dataclass(frozen=True)
class StateSettings:
    dir: str
    spool_max_bytes: int = 64 * 1024**2
    audit_retention_days: int = 90


@dataclass(frozen=True)
class ToolSettings:
    path: str
    memory_limit_bytes: int | None = None


@dataclass(frozen=True)
class ExecutorBinding:
    executor: str
    tool_ids: tuple[str, ...]
    env_names: tuple[str, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceSettings:
    repository_allowlist: frozenset[str]
    fetcher: str
    local_directory_root: str | None = None


@dataclass(frozen=True)
class SharedFolderSettings:
    local_path: str
    unc_host: str
    share_name: str


@dataclass(frozen=True)
class HttpsStorageSettings:
    base_url: str
    credential_secret: str


@dataclass(frozen=True)
class ArtifactStoreSettings:
    kind: str = "disabled"
    shared_folder: SharedFolderSettings | None = None
    https_storage: HttpsStorageSettings | None = None
    max_files: int = 100
    max_file_bytes: int = 2 * 1024**3
    max_total_bytes: int = 4 * 1024**3
    retention_days: int = 30
    store_quota_bytes: int = 200 * 1024**3


@dataclass(frozen=True)
class LogSettings:
    max_bytes_per_job: int = 10 * 1024**2
    max_bytes_per_second: int = 1024**2
    flush_interval_ms: int = 1000
    mask_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class LauncherSettings:
    kind: str
    tool_account_secret: str | None = None


@dataclass(frozen=True)
class TimeoutSettings:
    prepare_timeout_seconds: int = 600
    stop_wait_seconds: int = 5


@dataclass(frozen=True)
class AgentSettings:
    profile: str
    core: CoreSettings
    work: WorkSettings
    state: StateSettings
    source: SourceSettings
    launcher: LauncherSettings
    poll_interval_seconds: float = 5.0
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    env_allow: Mapping[str, str] = field(default_factory=dict)
    tools: Mapping[str, ToolSettings] = field(default_factory=dict)
    executors: Mapping[str, ExecutorBinding] = field(default_factory=dict)
    artifact_store: ArtifactStoreSettings = field(default_factory=ArtifactStoreSettings)
    logs: LogSettings = field(default_factory=LogSettings)
    timeouts: TimeoutSettings = field(default_factory=TimeoutSettings)
    firewall_self_check: bool = True

    @property
    def is_dev(self) -> bool:
        return self.profile == "dev"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AgentSettings:
        return _Parser(raw).parse()


class _Parser:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.raw = raw
        self.violations: list[tuple[str, str]] = []

    def bad(self, where: str, why: str) -> None:
        self.violations.append((where, why))

    def parse(self) -> AgentSettings:
        raw = self.raw
        profile = raw.get("profile", "prod")
        if profile not in ("prod", "dev"):
            self.bad("profile", "prod または dev")
        dev = profile == "dev"
        core = self._core(raw.get("core"), dev)
        work = self._work(raw.get("work"))
        state = self._state(raw.get("state"))
        tools = self._tools(raw.get("tools") or {})
        env_allow = self._env_allow(raw.get("env_allow") or {})
        executors = self._executors(raw.get("executors") or {}, tools)
        source = self._source(raw.get("source"), dev)
        store = self._artifact_store(raw.get("artifact_store") or {}, dev)
        logs = self._logs(raw.get("logs") or {})
        launcher = self._launcher(raw.get("launcher"), dev)
        timeouts = self._timeouts(raw.get("timeouts") or {})
        poll = raw.get("poll_interval_seconds", 5)
        if isinstance(poll, bool) or not isinstance(poll, (int, float)) or not 1 <= poll <= 60:
            self.bad("poll_interval_seconds", "1 以上 60 以下")
            poll = 5
        known = {
            "profile",
            "core",
            "poll_interval_seconds",
            "capabilities",
            "work",
            "state",
            "env_allow",
            "tools",
            "executors",
            "source",
            "artifact_store",
            "logs",
            "launcher",
            "timeouts",
            "firewall_self_check",
        }
        for key in set(raw) - known:
            self.bad(str(key), "未知の項目")
        if self.violations:
            raise SettingsError(self.violations)
        assert core and work and state and source and launcher  # 違反がなければ None にならない
        return AgentSettings(
            profile=str(profile),
            core=core,
            work=work,
            state=state,
            source=source,
            launcher=launcher,
            poll_interval_seconds=float(poll),
            capabilities=dict(raw.get("capabilities") or {}),
            env_allow=env_allow,
            tools=tools,
            executors=executors,
            artifact_store=store,
            logs=logs,
            timeouts=timeouts,
            firewall_self_check=bool(raw.get("firewall_self_check", True)),
        )

    # ------------------------------------------------------------------ 各節

    def _absolute(self, where: str, value: Any) -> str:
        if not isinstance(value, str) or not value or not PureWindowsPath(value).is_absolute():
            self.bad(where, "絶対パスでなければならない")
            return ""
        return value

    def _int(self, where: str, value: Any, minimum: int, maximum: int | None = None) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum and value > maximum):
            self.bad(where, "範囲外")
            return minimum
        return value

    def _core(self, raw: Any, dev: bool) -> CoreSettings | None:
        if not isinstance(raw, Mapping):
            self.bad("core", "必須")
            return None
        url, secret = raw.get("url"), raw.get("runner_token_secret")
        if not isinstance(url, str) or not re.match(r"^https?://[^\s]+$", url):
            self.bad("core.url", "URL でなければならない")
        elif url.startswith("http://") and not dev:
            self.bad("core.url", "prod では HTTPS のみ")
        if not isinstance(secret, str) or not secret:
            self.bad("core.runner_token_secret", "資格情報の名前でなければならない")
        return CoreSettings(str(url), str(secret), raw.get("ca_bundle"))

    def _work(self, raw: Any) -> WorkSettings | None:
        if not isinstance(raw, Mapping):
            self.bad("work", "必須")
            return None
        return WorkSettings(
            self._absolute("work.root", raw.get("root")),
            self._int("work.min_free_bytes", raw.get("min_free_bytes", 10 * 1024**3), 0),
        )

    def _state(self, raw: Any) -> StateSettings | None:
        if not isinstance(raw, Mapping):
            self.bad("state", "必須")
            return None
        return StateSettings(
            self._absolute("state.dir", raw.get("dir")),
            self._int("state.spool_max_bytes", raw.get("spool_max_bytes", 64 * 1024**2), 0),
            self._int("state.audit_retention_days", raw.get("audit_retention_days", 90), 1),
        )

    def _tools(self, raw: Any) -> dict[str, ToolSettings]:
        out: dict[str, ToolSettings] = {}
        if not isinstance(raw, Mapping):
            self.bad("tools", "オブジェクトでなければならない")
            return out
        for tool_id, spec in raw.items():
            where = f"tools.{tool_id}"
            if not _ID.match(str(tool_id)):
                self.bad(where, "識別子の形式の違反")
            path = self._absolute(f"{where}.path", spec.get("path") if isinstance(spec, Mapping) else None)
            if path.lower().endswith(_FORBIDDEN_TOOL_SUFFIXES):
                self.bad(f"{where}.path", ".bat・.cmd は登録できない")
            memory = spec.get("memory_limit_bytes") if isinstance(spec, Mapping) else None
            out[str(tool_id)] = ToolSettings(path, memory)
        return out

    def _env_allow(self, raw: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        if not isinstance(raw, Mapping):
            self.bad("env_allow", "オブジェクトでなければならない")
            return out
        for name, value in raw.items():
            if not _NAME.match(str(name)):
                self.bad(f"env_allow.{name}", "名前の形式の違反")
            elif not isinstance(value, str) or len(value) > 1024:
                self.bad(f"env_allow.{name}", "固定の値(1024 文字以内の文字列)でなければならない")
            else:
                out[str(name)] = value
        return out

    def _executors(self, raw: Any, tools: Mapping[str, ToolSettings]) -> dict[str, ExecutorBinding]:
        out: dict[str, ExecutorBinding] = {}
        if not isinstance(raw, Mapping):
            self.bad("executors", "オブジェクトでなければならない")
            return out
        for job_type, spec in raw.items():
            where = f"executors.{job_type}"
            if not isinstance(spec, Mapping):
                self.bad(where, "オブジェクトでなければならない")
                continue
            name = spec.get("executor")
            if not isinstance(name, str) or not _ID.match(name):
                self.bad(f"{where}.executor", "名前の形式の違反")
            tool_ids = tuple(spec.get("tool_ids") or ())
            for tool_id in tool_ids:
                if tool_id not in tools:
                    self.bad(f"{where}.tool_ids", "登録簿にない tool_id")
            env_names = tuple(spec.get("env_names") or ())
            for env_name in env_names:
                if not isinstance(env_name, str) or not _NAME.match(env_name):
                    self.bad(f"{where}.env_names", "名前の形式の違反")
            out[str(job_type)] = ExecutorBinding(str(name), tool_ids, env_names, dict(spec.get("options") or {}))
        return out

    def _source(self, raw: Any, dev: bool) -> SourceSettings | None:
        if not isinstance(raw, Mapping):
            self.bad("source", "必須")
            return None
        fetcher = raw.get("fetcher")
        if fetcher not in ("local_directory", "remote"):
            self.bad("source.fetcher", "local_directory または remote")
        elif fetcher == "local_directory" and not dev:
            self.bad("source.fetcher", "local_directory は dev のみ")
        allow = raw.get("repository_allowlist")
        if not isinstance(allow, (list, tuple)) or not all(isinstance(x, str) and x for x in allow):
            self.bad("source.repository_allowlist", "文字列の配列でなければならない")
            allow = []
        root = raw.get("local_directory_root")
        if fetcher == "local_directory":
            root = self._absolute("source.local_directory_root", root)
        return SourceSettings(frozenset(allow), str(fetcher), root)

    def _artifact_store(self, raw: Any, dev: bool) -> ArtifactStoreSettings:
        if not isinstance(raw, Mapping):
            self.bad("artifact_store", "オブジェクトでなければならない")
            return ArtifactStoreSettings()
        kind = raw.get("kind", "disabled")
        if kind not in ("disabled", "shared_folder", "https_storage"):
            self.bad("artifact_store.kind", "disabled、shared_folder、https_storage のいずれか")
        shared = https = None
        if kind == "shared_folder":
            sf = raw.get("shared_folder")
            if not isinstance(sf, Mapping) or not all(
                isinstance(sf.get(k), str) and sf.get(k) for k in ("local_path", "unc_host", "share_name")
            ):
                self.bad("artifact_store.shared_folder", "local_path、unc_host、share_name が必要")
            else:
                shared = SharedFolderSettings(
                    self._absolute("artifact_store.shared_folder.local_path", sf["local_path"]),
                    sf["unc_host"],
                    sf["share_name"],
                )
        if kind == "https_storage":
            hs = raw.get("https_storage")
            if (
                not isinstance(hs, Mapping)
                or not str(hs.get("base_url", "")).startswith("https://")
                or not hs.get("credential_secret")
            ):
                self.bad("artifact_store.https_storage", "https の base_url と credential_secret が必要")
            else:
                https = HttpsStorageSettings(hs["base_url"], hs["credential_secret"])
        return ArtifactStoreSettings(
            kind=str(kind),
            shared_folder=shared,
            https_storage=https,
            max_files=self._int("artifact_store.max_files", raw.get("max_files", 100), 1),
            max_file_bytes=self._int("artifact_store.max_file_bytes", raw.get("max_file_bytes", 2 * 1024**3), 1),
            max_total_bytes=self._int("artifact_store.max_total_bytes", raw.get("max_total_bytes", 4 * 1024**3), 1),
            retention_days=self._int("artifact_store.retention_days", raw.get("retention_days", 30), 1),
            store_quota_bytes=self._int(
                "artifact_store.store_quota_bytes", raw.get("store_quota_bytes", 200 * 1024**3), 1
            ),
        )

    def _logs(self, raw: Any) -> LogSettings:
        if not isinstance(raw, Mapping):
            self.bad("logs", "オブジェクトでなければならない")
            return LogSettings()
        patterns = tuple(raw.get("mask_patterns") or ())
        for pattern in patterns:
            try:
                re.compile(pattern)
            except (re.error, TypeError):
                self.bad("logs.mask_patterns", "正規表現として不正")
        return LogSettings(
            self._int("logs.max_bytes_per_job", raw.get("max_bytes_per_job", 10 * 1024**2), 1),
            self._int("logs.max_bytes_per_second", raw.get("max_bytes_per_second", 1024**2), 1),
            self._int("logs.flush_interval_ms", raw.get("flush_interval_ms", 1000), 100),
            patterns,
        )

    def _launcher(self, raw: Any, dev: bool) -> LauncherSettings | None:
        if not isinstance(raw, Mapping):
            self.bad("launcher", "必須")
            return None
        kind = raw.get("kind")
        if kind not in ("logon", "direct"):
            self.bad("launcher.kind", "logon または direct")
        elif kind == "direct" and not dev:
            self.bad("launcher.kind", "direct は dev のみ")
        elif kind == "logon" and not raw.get("tool_account_secret"):
            self.bad("launcher.tool_account_secret", "logon では必須")
        return LauncherSettings(str(kind), raw.get("tool_account_secret"))

    def _timeouts(self, raw: Any) -> TimeoutSettings:
        if not isinstance(raw, Mapping):
            self.bad("timeouts", "オブジェクトでなければならない")
            return TimeoutSettings()
        return TimeoutSettings(
            self._int("timeouts.prepare_timeout_seconds", raw.get("prepare_timeout_seconds", 600), 10),
            self._int("timeouts.stop_wait_seconds", raw.get("stop_wait_seconds", 5), 1, 30),
        )
