"""設定ファイルの読み込み(TOML → AgentSettings)。検証は job_runner_agent.settings が行う。"""

from __future__ import annotations

import tomllib
from pathlib import Path

from job_runner_agent.settings import AgentSettings


def load_settings(path: str | Path) -> AgentSettings:
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)
    return AgentSettings.from_mapping(raw)
