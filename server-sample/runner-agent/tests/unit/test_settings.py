"""AgentSettings の検証(T012)。既定は拒否。contracts/agent-config.schema.json への適合。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from job_runner_agent.settings import AgentSettings, SettingsError

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "specs/004-runner-agent/contracts/agent-config.schema.json").read_text(
        encoding="utf-8"
    )
)


def base() -> dict[str, Any]:
    return {
        "profile": "prod",
        "core": {"url": "https://core.example", "runner_token_secret": "runner-token"},
        "work": {"root": "C:\\runner\\work"},
        "state": {"dir": "C:\\runner\\state"},
        "tools": {"tool-a": {"path": "C:\\tools\\a.exe"}},
        "executors": {"type-a": {"executor": "exec-a", "tool_ids": ["tool-a"]}},
        "source": {"repository_allowlist": ["repo-1"], "fetcher": "remote"},
        "launcher": {"kind": "logon", "tool_account_secret": "tool-account"},
    }


def test_valid_settings_conform_to_schema_and_load() -> None:
    raw = base()
    jsonschema.validate(raw, SCHEMA)
    settings = AgentSettings.from_mapping(raw)
    assert settings.artifact_store.kind == "disabled"  # 既定は拒否
    assert settings.env_allow == {}
    assert settings.poll_interval_seconds == 5


def test_empty_allowlist_is_default_and_loads() -> None:
    raw = base()
    raw["source"]["repository_allowlist"] = []
    assert AgentSettings.from_mapping(raw).source.repository_allowlist == frozenset()


def mutate(path: str, value: Any) -> dict[str, Any]:
    raw = copy.deepcopy(base())
    node = raw
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[key]
    if value is DELETE:
        del node[keys[-1]]
    else:
        node[keys[-1]] = value
    return raw


DELETE = object()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("core.url", "http://core.example"),  # prod は HTTPS のみ
        ("source.fetcher", "local_directory"),  # dev のみ
        ("launcher", {"kind": "direct"}),  # dev のみ
        ("launcher", {"kind": "logon"}),  # 資格の名前が必要
        ("tools", {"t": {"path": "C:\\x\\run.bat"}}),
        ("tools", {"t": {"path": "C:\\x\\run.CMD"}}),
        ("tools", {"t": {"path": "tools\\a.exe"}}),  # 絶対パスでない
        ("work.root", "relative\\path"),
        ("executors", {"type-a": {"executor": "exec-a", "tool_ids": ["unknown-tool"]}}),
        ("env_allow", {"1BAD": "x"}),
        ("env_allow", {"OK": 3}),
        ("poll_interval_seconds", 0),
        ("artifact_store", {"kind": "shared_folder"}),
        (
            "artifact_store",
            {"kind": "https_storage", "https_storage": {"base_url": "http://x", "credential_secret": "c"}},
        ),
        ("logs", {"mask_patterns": ["("]}),
        ("profile", "other"),
        ("unknown_key", 1),
    ],
)
def test_invalid_settings_are_rejected(path: str, value: Any) -> None:
    with pytest.raises(SettingsError) as info:
        AgentSettings.from_mapping(mutate(path, value))
    assert info.value.violations


def test_dev_allows_dev_choices() -> None:
    raw = base()
    raw["profile"] = "dev"
    raw["core"]["url"] = "http://127.0.0.1:8000"
    raw["launcher"] = {"kind": "direct"}
    raw["source"] = {"repository_allowlist": ["r"], "fetcher": "local_directory", "local_directory_root": "C:\\src"}
    assert AgentSettings.from_mapping(raw).is_dev


def test_violation_text_does_not_echo_values() -> None:
    raw = base()
    raw["env_allow"] = {"NAME": "x" * 2000}
    raw["tools"] = {"t": {"path": "C:\\SECRET-TOKEN\\run.bat"}}
    with pytest.raises(SettingsError) as info:
        AgentSettings.from_mapping(raw)
    assert "SECRET-TOKEN" not in str(info.value)
