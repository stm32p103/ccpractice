"""偽の認証基盤の混入の検査(T-A9)。

`profile != "dev"` で Fake・メモリを選ぶ設定は、起動が拒否される(環境変数の SecretSource は警告)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from job_core_server.__main__ import main
from job_core_server.settings import ConfigError, load_settings
from job_core_server.wiring import build_app

CONFIG = Path(__file__).resolve().parents[1] / "config"


def write(tmp_path: Path, profile: str, provider: str = "fake", kind: str = "memory") -> Path:
    access = tmp_path / "access.toml"
    access.write_text((CONFIG / "access.dev.toml").read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "server.toml"
    path.write_text(
        f'profile = "{profile}"\n[access]\nconfig_path = "access.toml"\n[identity]\nprovider = "{provider}"\n'
        f'[persistence]\nkind = "{kind}"\ndsn_secret = "JOB_DATABASE_URL"\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("profile", ["prod", "trial"])
@pytest.mark.parametrize(("provider", "kind"), [("fake", "memory"), ("fake", "postgres"), ("external", "memory")])
def test_test_implementations_are_refused_outside_dev(tmp_path: Path, profile: str, provider: str, kind: str) -> None:
    with pytest.raises(ConfigError):
        load_settings(write(tmp_path, profile, provider, kind))


def test_the_server_refuses_to_start_with_a_forbidden_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(write(tmp_path, "prod"))]) == 2
    assert "起動できない" in capsys.readouterr().err


def test_unconnected_production_implementations_refuse_to_start_instead_of_falling_back(tmp_path: Path) -> None:
    path = write(tmp_path, "prod", "external", "postgres")
    settings = load_settings(path)
    with pytest.raises(ConfigError):
        build_app(settings)  # 本番の実装が未接続でも、Fake・メモリへ黙って切り替えない


def test_dev_configuration_builds_the_app() -> None:
    settings = load_settings(CONFIG / "server.dev.toml")
    assert settings.is_dev
    assert build_app(settings).title
