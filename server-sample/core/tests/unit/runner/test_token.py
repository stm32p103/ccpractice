"""RunnerToken・ハッシュの単体テスト(data-model.md §5。research.md R9。SC-008)。"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from job_core.runner.domain.errors import RunnerAuthenticationFailed
from job_core.runner.domain.token import IssuedToken, RunnerToken, hash_token
from job_core.shared.ids import RunnerId
from job_core.shared.secret_generator import TOKEN_PREFIX, SystemSecretGenerator

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
TOKEN = "rt_example-token-value"


def issued() -> RunnerToken:
    return RunnerToken.issue(token_id="T1", runner_id=RunnerId("R1"), token_hash=hash_token(TOKEN), at=T0)


def test_hash_is_sha256_hex_64() -> None:
    h = hash_token(TOKEN)
    assert re.fullmatch(r"[0-9a-f]{64}", h.value)
    assert h == hash_token(TOKEN)
    assert h != hash_token(TOKEN + "x")
    # SHA-256("abc") の既知の値
    assert hash_token("abc").value == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_matches_uses_constant_time_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    import hmac

    calls: list[tuple[bytes, bytes]] = []
    original = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr("job_core.runner.domain.token.hmac.compare_digest", spy)
    token = issued()
    assert token.matches(hash_token(TOKEN))
    assert not token.matches(hash_token("other"))
    assert len(calls) == 2


def test_revoke_is_idempotent() -> None:
    token = issued()
    assert not token.is_revoked
    assert token.revoke(T0 + timedelta(seconds=1)) is True
    assert token.is_revoked
    first = token.revoked_at
    assert token.revoke(T0 + timedelta(seconds=9)) is False
    assert token.revoked_at == first


def test_matches_still_answers_for_revoked_token() -> None:
    token = issued()
    token.revoke(T0)
    assert token.matches(hash_token(TOKEN))  # 失効の判定は is_revoked で行う


def test_repr_and_str_never_contain_hash_or_value() -> None:
    token = issued()
    digest = hash_token(TOKEN).value
    for text in (repr(token), str(token), repr(token.token_hash), str(token.token_hash)):
        assert digest not in text
        assert digest[:12] not in text
        assert TOKEN not in text
    wrapped = IssuedToken(token_id="T1", value=TOKEN)
    assert TOKEN not in repr(wrapped)
    assert TOKEN not in str(wrapped)
    assert wrapped.value == TOKEN  # 値は発行の戻り値にだけある


def test_authentication_failed_message_has_no_detail() -> None:
    err = RunnerAuthenticationFailed()
    assert TOKEN not in str(err)
    assert err.details == {}


def test_issue_requires_id() -> None:
    with pytest.raises(ValueError):
        RunnerToken.issue(token_id="", runner_id=RunnerId("R1"), token_hash=hash_token(TOKEN), at=T0)


def test_system_secret_generator_shape_and_uniqueness() -> None:
    generator = SystemSecretGenerator()
    tokens = {generator.new_token() for _ in range(50)}
    assert len(tokens) == 50
    for token in tokens:
        assert token.startswith(TOKEN_PREFIX)
        assert re.fullmatch(r"rt_[A-Za-z0-9_-]{43}", token)  # 32 バイト = 43 文字(URL 安全な Base64、パディングなし)
