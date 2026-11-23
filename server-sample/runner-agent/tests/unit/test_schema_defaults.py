"""設定のスキーマ(contracts/agent-config.schema.json)の既定値と、AgentSettings の既定値が一致する(T092)。

data-model.md が正とする制約(上限・既定)を、スキーマと実装の両方が守っていることを検査する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_runner_agent.settings import (
    ArtifactStoreSettings,
    LogSettings,
    StateSettings,
    TimeoutSettings,
    WorkSettings,
)

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "specs/004-runner-agent/contracts/agent-config.schema.json").read_text(
        encoding="utf-8"
    )
)["properties"]


def default_of(section: dict[str, Any], key: str) -> Any:
    return section["properties"][key]["default"]


@pytest.mark.parametrize(
    ("schema_key", "settings", "mapping"),
    [
        ("work", WorkSettings("C:\\w"), {"min_free_bytes": "min_free_bytes"}),
        (
            "state",
            StateSettings("C:\\s"),
            {"spool_max_bytes": "spool_max_bytes", "audit_retention_days": "audit_retention_days"},
        ),
        (
            "logs",
            LogSettings(),
            {
                "max_bytes_per_job": "max_bytes_per_job",
                "max_bytes_per_second": "max_bytes_per_second",
                "flush_interval_ms": "flush_interval_ms",
            },
        ),
        (
            "timeouts",
            TimeoutSettings(),
            {"prepare_timeout_seconds": "prepare_timeout_seconds", "stop_wait_seconds": "stop_wait_seconds"},
        ),
        (
            "artifact_store",
            ArtifactStoreSettings(),
            {
                "max_files": "max_files",
                "max_file_bytes": "max_file_bytes",
                "max_total_bytes": "max_total_bytes",
                "retention_days": "retention_days",
                "store_quota_bytes": "store_quota_bytes",
            },
        ),
    ],
)
def test_defaults_match_the_schema(schema_key: str, settings: object, mapping: dict[str, str]) -> None:
    for schema_name, attribute in mapping.items():
        assert getattr(settings, attribute) == default_of(SCHEMA[schema_key], schema_name), (schema_key, schema_name)


def test_top_level_defaults_and_artifact_kind_default() -> None:
    assert SCHEMA["poll_interval_seconds"]["default"] == 5
    assert SCHEMA["artifact_store"]["properties"]["kind"]["default"] == "disabled"
    assert ArtifactStoreSettings().kind == "disabled"  # 既定は拒否(収集しない)
