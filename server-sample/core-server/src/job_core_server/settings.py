"""core-server の設定(TOML の読み込みと検証。research.md R13、T-A9)。

`profile = "dev"` 以外では、Fake の認証基盤・メモリ上のリポジトリの選択を拒否する
(試験用の実装が本番で有効になるのを防ぐ)。
環境変数の SecretSource(開発・試験専用)を `dev` 以外で選ぶと、警告する。秘密情報は設定ファイルに書かない
(接続の秘密は `SecretSource` から名前で取得する)。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEV_PROFILE = "dev"
PROFILES = frozenset({"dev", "trial", "prod"})
IDENTITY_PROVIDERS = frozenset({"fake", "external"})
PERSISTENCE_KINDS = frozenset({"memory", "postgres"})
SECRET_SOURCES = frozenset({"env"})


class ConfigError(Exception):
    """設定が不正。違反は場所と理由だけ(値を含めない)。"""

    def __init__(self, violations: list[tuple[str, str]]) -> None:
        self.violations = violations
        super().__init__("設定が不正: " + "; ".join(f"{location}: {reason}" for location, reason in violations))


@dataclass(frozen=True)
class ServerSettings:
    profile: str
    host: str
    port: int
    allowed_networks: tuple[str, ...] | None
    cookie_secure: bool
    allowed_origins: tuple[str, ...]
    access_config_path: Path
    identity_provider: str
    persistence_kind: str
    database_secret: str | None
    secret_source: str
    warnings: tuple[str, ...] = field(default=(), compare=False)

    @property
    def is_dev(self) -> bool:
        return self.profile == DEV_PROFILE


def _table(data: dict[str, Any], name: str, violations: list[tuple[str, str]]) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        violations.append((name, "表でなければならない"))
        return {}
    return value


def _choice(
    table: dict[str, Any], key: str, default: str, allowed: frozenset[str], where: str, v: list[tuple[str, str]]
) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or value not in allowed:
        v.append((f"{where}.{key}", f"{sorted(allowed)} のいずれかでなければならない"))
        return default
    return value


def parse_settings(data: dict[str, Any], base_dir: Path) -> ServerSettings:
    """検証済みの設定を作る。不正なら ConfigError。"""
    violations: list[tuple[str, str]] = []
    warnings: list[str] = []
    profile = data.get("profile", "")
    if profile not in PROFILES:
        violations.append(("profile", f"{sorted(PROFILES)} のいずれかでなければならない"))
        profile = ""
    server = _table(data, "server", violations)
    api = _table(data, "api", violations)
    access = _table(data, "access", violations)
    identity = _table(data, "identity", violations)
    persistence = _table(data, "persistence", violations)
    secrets = _table(data, "secrets", violations)

    host = server.get("host", "127.0.0.1")
    port = server.get("port", 8080)
    if not isinstance(host, str) or not host:
        violations.append(("server.host", "空でない文字列でなければならない"))
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        violations.append(("server.port", "1〜65535 の整数でなければならない"))

    networks = api.get("allowed_networks")
    if networks is not None and (not isinstance(networks, list) or not all(isinstance(n, str) for n in networks)):
        violations.append(("api.allowed_networks", "文字列の配列でなければならない"))
        networks = None
    origins = api.get("allowed_origins", [])
    if not isinstance(origins, list) or not all(isinstance(o, str) for o in origins):
        violations.append(("api.allowed_origins", "文字列の配列でなければならない"))
        origins = []
    cookie_secure = api.get("cookie_secure", True)
    if not isinstance(cookie_secure, bool):
        violations.append(("api.cookie_secure", "真偽値でなければならない"))
        cookie_secure = True

    access_path = access.get("config_path")
    if not isinstance(access_path, str) or not access_path:
        violations.append(("access.config_path", "アクセス設定のファイルのパスが必要"))
        access_path = "access.toml"

    provider = _choice(identity, "provider", "external", IDENTITY_PROVIDERS, "identity", violations)
    kind = _choice(persistence, "kind", "postgres", PERSISTENCE_KINDS, "persistence", violations)
    secret_source = _choice(secrets, "source", "env", SECRET_SOURCES, "secrets", violations)
    database_secret = persistence.get("dsn_secret")
    if database_secret is not None and not isinstance(database_secret, str):
        violations.append(("persistence.dsn_secret", "秘密の名前(文字列)でなければならない"))
        database_secret = None
    if kind == "postgres" and not database_secret:
        violations.append(("persistence.dsn_secret", "postgres では、接続の秘密の名前が必要(値は設定に書かない)"))

    # T-A9: dev 以外では、試験用の実装の選択を拒否する
    if profile and profile != DEV_PROFILE:
        if provider == "fake":
            violations.append(("identity.provider", 'fake は profile = "dev" でだけ使える'))
        if kind == "memory":
            violations.append(("persistence.kind", 'memory は profile = "dev" でだけ使える'))
        if secret_source == "env":
            warnings.append("環境変数の SecretSource は開発・試験専用。本番では保管機能の実装を使うこと")

    if violations:
        raise ConfigError(violations)
    return ServerSettings(
        profile=profile,
        host=host,
        port=port,
        allowed_networks=tuple(networks) if networks is not None else None,
        cookie_secure=cookie_secure,
        allowed_origins=tuple(origins),
        access_config_path=(base_dir / access_path).resolve(),
        identity_provider=provider,
        persistence_kind=kind,
        database_secret=database_secret,
        secret_source=secret_source,
        warnings=tuple(warnings),
    )


def load_settings(path: str | Path) -> ServerSettings:
    """TOML の設定ファイルを読み、検証する。ファイルの内容(値)は、エラーに含めない。"""
    file = Path(path)
    try:
        with file.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError:
        raise ConfigError([("file", "設定ファイルがない")]) from None
    except OSError:
        raise ConfigError([("file", "設定ファイルを読めない")]) from None
    except tomllib.TOMLDecodeError:
        raise ConfigError([("file", "TOML として解釈できない")]) from None
    return parse_settings(data, file.resolve().parent)
