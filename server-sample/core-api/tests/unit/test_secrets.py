"""トークンの補助(research.md R4、T-A1)。"""

from __future__ import annotations

import pytest

from job_core_api.access.secrets import TokenKind, hash_token, hashes_equal, new_token, token_kind_of


def test_prefix_determines_kind() -> None:
    assert token_kind_of(new_token(TokenKind.SESSION)) is TokenKind.SESSION
    assert token_kind_of(new_token(TokenKind.SERVICE)) is TokenKind.SERVICE
    assert token_kind_of("rt_abc") is TokenKind.RUNNER
    assert token_kind_of("xx_abc") is None
    assert token_kind_of("") is None


def test_tokens_are_random_and_long_enough() -> None:
    values = {new_token(TokenKind.SESSION) for _ in range(50)}
    assert len(values) == 50
    assert all(len(v) >= 3 + 43 for v in values)


def test_runner_tokens_are_not_issued_here() -> None:
    with pytest.raises(ValueError):
        new_token(TokenKind.RUNNER)


def test_hash_is_sha256_hex_and_stable() -> None:
    h = hash_token("st_value")
    assert len(h) == 64 and int(h, 16) >= 0
    assert h == hash_token("st_value") != hash_token("st_other")
    assert "st_value" not in h


def test_hashes_equal_is_exact() -> None:
    h = hash_token("a")
    assert hashes_equal(h, hash_token("a"))
    assert not hashes_equal(h, hash_token("b"))
