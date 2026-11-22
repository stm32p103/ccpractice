"""認証・セッションのモデル(data-model.md §1)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.shared.ids import SubjectId
from job_core_api.access.models import InvalidModel, VerifiedIdentity
from job_testing.contracts.service_credentials import T0, make_credential, make_session


def test_verified_identity_validates_fields() -> None:
    assert VerifiedIdentity(SubjectId("u1"), frozenset({"g"}), "名前").groups == {"g"}
    with pytest.raises(InvalidModel):
        VerifiedIdentity(SubjectId(""), frozenset())
    with pytest.raises(InvalidModel):
        VerifiedIdentity(SubjectId("x" * 257), frozenset())
    with pytest.raises(InvalidModel):
        VerifiedIdentity(SubjectId("u"), frozenset({"g" * 257}))
    with pytest.raises(InvalidModel):
        VerifiedIdentity(SubjectId("u"), frozenset({f"g{i}" for i in range(129)}))
    with pytest.raises(InvalidModel):
        VerifiedIdentity(SubjectId("u"), frozenset(), "bad\nname")


def test_credential_name_constraints() -> None:
    with pytest.raises(InvalidModel):
        make_credential(name="")
    with pytest.raises(InvalidModel):
        make_credential(name="n" * 129)


def test_credential_revoke_is_one_way_and_used_never_goes_back() -> None:
    c = make_credential()
    revoked = c.revoke(T0 + timedelta(minutes=1))
    assert revoked.is_revoked and revoked.version == c.version + 1
    assert revoked.revoke(T0 + timedelta(minutes=9)) is revoked
    used = c.used(T0 + timedelta(minutes=5))
    assert used.used(T0 + timedelta(minutes=1)) is used


def test_repr_hides_hashes() -> None:
    c = make_credential()
    s = make_session()
    assert c.token_hash not in repr(c)
    assert s.token_hash not in repr(s)


def test_session_activity_rules() -> None:
    idle = timedelta(hours=2)
    s = make_session()
    assert s.is_active(T0 + timedelta(hours=1), idle)
    assert not s.is_active(T0 + timedelta(hours=2), idle)  # 無操作の期限
    assert not s.is_active(T0 + timedelta(hours=12), timedelta(hours=24))  # 絶対期限
    assert s.idle_expires_at(idle) == T0 + idle
    from dataclasses import replace

    assert not replace(s, revoked_at=T0).is_active(T0, idle)
