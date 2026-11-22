"""IdentityProvider のポートの契約テスト(contracts/ports.md「IdentityProvider」)。

使い方: テストのクラスで継承し、`identity_env` フィクスチャ(IdentityEnv)を定義する。
実アダプタ(005)も同じクラスを継承して実行する。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pytest

from job_core_api.access.ports import IdentityProvider, IdentityProviderUnavailable, IdentityRejected


@dataclass
class IdentityEnv:
    provider: IdentityProvider
    valid_proof: Mapping[str, str]
    """確認できる証明。同じ値で何度呼んでも同じ subject_id になる。"""
    invalid_proof: Mapping[str, str]
    """確認できない証明。"""
    expected_subject: str
    set_available: Callable[[bool], None]
    """認証基盤の利用の可否を切り替える。"""


class IdentityProviderContract:
    def test_valid_proof_returns_a_stable_subject(self, identity_env: IdentityEnv) -> None:
        first = identity_env.provider.complete_login(identity_env.valid_proof)
        second = identity_env.provider.complete_login(identity_env.valid_proof)
        assert first.subject_id == second.subject_id == identity_env.expected_subject
        assert first.subject_id.strip() != ""
        assert isinstance(first.groups, frozenset)

    def test_invalid_proof_is_rejected_without_leaking_the_value(self, identity_env: IdentityEnv) -> None:
        with pytest.raises(IdentityRejected) as info:
            identity_env.provider.complete_login(identity_env.invalid_proof)
        text = str(info.value) + repr(info.value)
        for value in identity_env.invalid_proof.values():
            assert value not in text or value == ""

    def test_unavailable_provider_raises_unavailable(self, identity_env: IdentityEnv) -> None:
        identity_env.set_available(False)
        try:
            with pytest.raises(IdentityProviderUnavailable):
                identity_env.provider.complete_login(identity_env.valid_proof)
        finally:
            identity_env.set_available(True)
