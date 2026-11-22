"""設定の雛形が、検証を通ること(contracts/access-config.schema.json、設定の検証)。秘密情報を含まない。"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import jsonschema
import pytest

from job_core_api.access.config_file import TomlAccessConfigSource
from job_core_server.settings import load_settings

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "core-server" / "config"
SCHEMA = json.loads((ROOT / "specs/003-core-api/contracts/access-config.schema.json").read_text("utf-8"))
TERMS = [
    t.strip().lower()
    for t in (ROOT / "core/tests/architecture/forbidden_terms.txt").read_text("utf-8").splitlines()
    if t.strip() and not t.startswith("#")
]


@pytest.mark.parametrize("name", ["access.example.toml", "access.dev.toml"])
def test_access_templates_conform_to_the_schema_and_validate(name: str) -> None:
    data = tomllib.loads((CONFIG / name).read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    config = TomlAccessConfigSource(CONFIG / name).load()
    assert config.digest and "viewer" in config.roles


@pytest.mark.parametrize("name", ["server.example.toml", "server.dev.toml"])
def test_server_templates_load(name: str) -> None:
    settings = load_settings(CONFIG / name)
    assert settings.access_config_path.parent == CONFIG


def test_templates_contain_no_secrets_or_product_specific_terms() -> None:
    for file in CONFIG.glob("*.toml"):
        text = file.read_text(encoding="utf-8").lower()
        assert [t for t in TERMS if t in text] == [], file.name
        assert "password" not in text and "api_key" not in text and "bearer" not in text
