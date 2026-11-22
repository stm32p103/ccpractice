"""core-server の設定の読み込みと検証(T-A9。research.md R13)。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_core_server.settings import ConfigError, load_settings, parse_settings

BASE = Path("/base")


def dev(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "profile": "dev",
        "access": {"config_path": "access.toml"},
        "identity": {"provider": "fake"},
        "persistence": {"kind": "memory"},
    }
    data.update(changes)
    return data


def prod(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "profile": "prod",
        "access": {"config_path": "access.toml"},
        "identity": {"provider": "external"},
        "persistence": {"kind": "postgres", "dsn_secret": "JOB_DATABASE_URL"},
    }
    data.update(changes)
    return data


def test_dev_memory_fake_is_accepted_with_defaults() -> None:
    settings = parse_settings(dev(), BASE)
    assert settings.is_dev and settings.host == "127.0.0.1" and settings.port == 8080
    assert settings.persistence_kind == "memory" and settings.identity_provider == "fake"
    assert settings.access_config_path == (BASE / "access.toml").resolve()


def test_prod_with_external_provider_and_postgres_is_accepted() -> None:
    settings = parse_settings(prod(), BASE)
    assert not settings.is_dev and settings.database_secret == "JOB_DATABASE_URL"
    assert any("開発・試験専用" in w for w in settings.warnings)  # 環境変数の SecretSource は警告


@pytest.mark.parametrize("profile", ["prod", "trial"])
def test_fake_provider_and_memory_repositories_are_rejected_outside_dev(profile: str) -> None:
    with pytest.raises(ConfigError) as info:
        parse_settings(dev(profile=profile), BASE)
    locations = {loc for loc, _ in info.value.violations}
    assert {"identity.provider", "persistence.kind"} <= locations


def test_postgres_requires_a_secret_name_and_never_a_value() -> None:
    data = prod(persistence={"kind": "postgres"})
    with pytest.raises(ConfigError) as info:
        parse_settings(data, BASE)
    assert any(loc == "persistence.dsn_secret" for loc, _ in info.value.violations)


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": "staging"},
        {"server": {"port": 0}},
        {"server": {"port": "80"}},
        {"api": {"allowed_networks": "10.0.0.0/8"}},
        {"api": {"cookie_secure": "yes"}},
        {"identity": {"provider": "other"}},
        {"access": {}},
        {"secrets": {"source": "vault"}},
    ],
)
def test_invalid_values_are_rejected(changes: dict[str, Any]) -> None:
    data = dev()
    data.update(changes)
    with pytest.raises(ConfigError):
        parse_settings(data, BASE)


def test_violations_contain_locations_and_reasons_only() -> None:
    with pytest.raises(ConfigError) as info:
        parse_settings(dev(profile="staging-SECRETLIKE"), BASE)
    assert "SECRETLIKE" not in str(info.value)


def test_load_settings_reports_missing_and_broken_files_without_content(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as missing:
        load_settings(tmp_path / "none.toml")
    assert missing.value.violations == [("file", "設定ファイルがない")]
    broken = tmp_path / "broken.toml"
    broken.write_text("password = = TOPSECRET", encoding="utf-8")
    with pytest.raises(ConfigError) as invalid:
        load_settings(broken)
    assert "TOPSECRET" not in str(invalid.value)
