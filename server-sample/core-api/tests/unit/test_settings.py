"""ApiSettings の既定値と検証(research.md R5・R11・R19)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core_api.settings import ApiSettings


def test_defaults_follow_the_design() -> None:
    s = ApiSettings()
    assert s.session_absolute_timeout == timedelta(hours=12)
    assert s.session_idle_timeout == timedelta(hours=2)
    assert s.max_body_bytes == 1024 * 1024
    assert (s.list_default_limit, s.list_max_limit) == (50, 200)
    assert s.sse_max_connections == 200
    assert s.sse_replay_size == 1000
    assert s.sse_subscriber_queue == 100
    assert s.sse_heartbeat_seconds == 15
    assert s.auth_failure_window == timedelta(minutes=1)
    assert s.cookie_name == "__Host-session"
    assert ApiSettings(cookie_secure=False).cookie_name == "session"


def test_no_cors_setting_exists() -> None:
    assert not any("cors" in name for name in ApiSettings.__dataclass_fields__)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allowed_networks": ("not-a-cidr",)},
        {"max_body_bytes": 0},
        {"sse_max_connections": -1},
        {"list_default_limit": 300},
        {"session_idle_timeout": timedelta(hours=13)},
        {"auth_failure_window": timedelta(0)},
    ],
)
def test_invalid_values_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ApiSettings(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("address", "allowed"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("10.1.2.3", True),
        ("192.168.0.5", True),
        ("::ffff:10.1.2.3", True),
        ("8.8.8.8", False),
        ("2001:db8::1", False),
        ("not-an-address", False),
    ],
)
def test_network_allowed(address: str, allowed: bool) -> None:
    assert ApiSettings().network_allowed(address) is allowed


def test_custom_allow_list() -> None:
    s = ApiSettings(allowed_networks=("203.0.113.0/24",))
    assert s.network_allowed("203.0.113.9")
    assert not s.network_allowed("127.0.0.1")
