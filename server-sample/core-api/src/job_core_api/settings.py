"""API の設定の値オブジェクト(research.md R5・R11・R19)。

既定値は運用で変えられる設定値として扱う。検証は構築時に行い、不正な値は ValueError にする。
CORS は許可しない(WebUI は同一オリジンで配信する。R11)ため、cors の設定項目を持たない。
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import timedelta

DEFAULT_ALLOWED_NETWORKS: tuple[str, ...] = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
)


@dataclass(frozen=True)
class ApiSettings:
    allowed_networks: tuple[str, ...] = DEFAULT_ALLOWED_NETWORKS
    """接続元の許可リスト(CIDR)。接続のアドレスだけを見る(R11)。"""
    session_absolute_timeout: timedelta = timedelta(hours=12)
    session_idle_timeout: timedelta = timedelta(hours=2)
    session_retention: timedelta = timedelta(days=7)
    """期限切れ・失効後のセッションの記録を残す期間(R20)。"""
    cookie_secure: bool = True
    """False のとき、Cookie の名前は `session`(`__Host-` の接頭辞は Secure を要する。R5)。"""
    allowed_origins: tuple[str, ...] = ()
    """Cookie で認証された状態変更で許す Origin。空なら同一オリジン(Host ヘッダとの一致)だけ。"""
    max_body_bytes: int = 1024 * 1024
    list_default_limit: int = 50
    list_max_limit: int = 200
    sse_max_connections: int = 200
    sse_replay_size: int = 1000
    sse_subscriber_queue: int = 100
    sse_heartbeat_seconds: int = 15
    auth_failure_window: timedelta = timedelta(minutes=1)
    openapi_requires_auth: bool = True
    deprecation_sunset: str | None = None
    """旧版を示すとき、`Sunset` ヘッダの値(RFC 9110 の日付)。None なら付けない。"""

    def __post_init__(self) -> None:
        networks = tuple(self.allowed_networks)
        object.__setattr__(self, "allowed_networks", networks)
        for cidr in networks:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError as exc:
                raise ValueError(f"allowed_networks に不正な CIDR がある: {cidr!r}") from exc
        object.__setattr__(self, "allowed_origins", tuple(self.allowed_origins))
        positives = {
            "session_absolute_timeout": self.session_absolute_timeout.total_seconds(),
            "session_idle_timeout": self.session_idle_timeout.total_seconds(),
            "session_retention": self.session_retention.total_seconds(),
            "auth_failure_window": self.auth_failure_window.total_seconds(),
            "max_body_bytes": self.max_body_bytes,
            "list_default_limit": self.list_default_limit,
            "list_max_limit": self.list_max_limit,
            "sse_max_connections": self.sse_max_connections,
            "sse_replay_size": self.sse_replay_size,
            "sse_subscriber_queue": self.sse_subscriber_queue,
            "sse_heartbeat_seconds": self.sse_heartbeat_seconds,
        }
        for name, value in positives.items():
            if value <= 0:
                raise ValueError(f"{name} は正の値でなければならない")
        if self.list_default_limit > self.list_max_limit:
            raise ValueError("list_default_limit は list_max_limit 以下でなければならない")
        if self.session_idle_timeout > self.session_absolute_timeout:
            raise ValueError("session_idle_timeout は session_absolute_timeout 以下でなければならない")

    @property
    def cookie_name(self) -> str:
        return "__Host-session" if self.cookie_secure else "session"

    def network_allowed(self, address: str) -> bool:
        """接続のアドレスが許可リストに含まれるか。解釈できないアドレスは許可しない。"""
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return any(ip in ipaddress.ip_network(cidr, strict=False) for cidr in self.allowed_networks)
