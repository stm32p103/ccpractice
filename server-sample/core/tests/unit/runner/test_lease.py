"""Lease 集約の単体テスト(data-model.md §4「遷移」の全行)。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from job_core.runner.domain.errors import InvalidLeaseTransition, LeaseExpired
from job_core.runner.domain.lease import Lease, LeaseStatus
from job_core.runner.domain.values import RunnerTimingPolicy
from job_core.shared.ids import JobId, RunnerId

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
POLICY = RunnerTimingPolicy()
LEASE = POLICY.lease_duration


def new_lease() -> Lease:
    return Lease.grant(lease_id="L1", job_id=JobId("j1"), runner_id=RunnerId("R1"), now=T0, policy=POLICY)


def test_grant() -> None:
    lease = new_lease()
    assert lease.status is LeaseStatus.ACTIVE
    assert lease.expires_at == T0 + LEASE
    assert lease.last_extended_at is None
    assert lease.granted_at == T0


def test_is_live_at_boundary() -> None:
    lease = new_lease()
    assert lease.is_live_at(T0 + LEASE)  # 期限ちょうどは有効
    assert not lease.is_live_at(T0 + LEASE + timedelta(microseconds=1))


def test_extend_before_expiry_uses_receive_time() -> None:
    lease = new_lease()
    at = T0 + timedelta(seconds=100)
    lease.extend(at, POLICY)
    assert lease.expires_at == at + LEASE
    assert lease.last_extended_at == at
    assert lease.status is LeaseStatus.ACTIVE


def test_extend_exactly_at_expiry_is_allowed() -> None:
    lease = new_lease()
    lease.extend(T0 + LEASE, POLICY)
    assert lease.expires_at == T0 + 2 * LEASE


def test_duplicate_extension_gives_same_result() -> None:
    lease = new_lease()
    at = T0 + timedelta(seconds=30)
    lease.extend(at, POLICY)
    first = lease.expires_at
    lease.extend(at, POLICY)
    assert lease.expires_at == first


def test_extend_after_expiry_raises_and_does_not_change() -> None:
    lease = new_lease()
    with pytest.raises(LeaseExpired):
        lease.extend(T0 + LEASE + timedelta(seconds=1), POLICY)
    assert lease.expires_at == T0 + LEASE
    assert lease.status is LeaseStatus.ACTIVE


def test_expire_requires_past_deadline() -> None:
    lease = new_lease()
    with pytest.raises(InvalidLeaseTransition):
        lease.expire(T0 + LEASE)
    lease.expire(T0 + LEASE + timedelta(seconds=1))
    assert lease.status is LeaseStatus.EXPIRED


def test_end() -> None:
    lease = new_lease()
    lease.end()
    assert lease.status is LeaseStatus.ENDED


@pytest.mark.parametrize("final", [LeaseStatus.EXPIRED, LeaseStatus.ENDED])
def test_terminal_statuses_allow_no_transition(final: LeaseStatus) -> None:
    lease = new_lease()
    after = T0 + LEASE + timedelta(seconds=1)
    if final is LeaseStatus.EXPIRED:
        lease.expire(after)
    else:
        lease.end()
    for action in (lambda: lease.extend(T0, POLICY), lambda: lease.expire(after), lease.end):
        with pytest.raises(InvalidLeaseTransition):
            action()
    assert lease.status is final
    assert not lease.is_live_at(T0)


def test_grant_requires_id() -> None:
    with pytest.raises(ValueError):
        Lease.grant(lease_id="", job_id=JobId("j1"), runner_id=RunnerId("R1"), now=T0, policy=POLICY)
