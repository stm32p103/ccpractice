"""Lease 集約(data-model.md §4。research.md R7)。

項目: Lease.lease_id、.job_id、.runner_id、.granted_at、.expires_at、.last_extended_at、.status、.version。
記録上の状態が ACTIVE のままでも、期限を過ぎたものは延長しない(FR-017)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from job_core.shared.ids import JobId, RunnerId

from .errors import InvalidLeaseTransition, LeaseExpired
from .values import RunnerTimingPolicy


class LeaseStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    ENDED = "ended"


@dataclass(eq=False)
class Lease:
    lease_id: str
    job_id: JobId
    runner_id: RunnerId
    granted_at: datetime
    expires_at: datetime
    last_extended_at: datetime | None = None
    status: LeaseStatus = LeaseStatus.ACTIVE
    version: int = 0

    @classmethod
    def grant(
        cls, *, lease_id: str, job_id: JobId, runner_id: RunnerId, now: datetime, policy: RunnerTimingPolicy
    ) -> Lease:
        """割り当てと同じ UoW で作る。期限は now + lease_duration。"""
        if not lease_id:
            raise ValueError("lease_id は空でない文字列でなければならない")
        return cls(
            lease_id=lease_id,
            job_id=job_id,
            runner_id=runner_id,
            granted_at=now,
            expires_at=now + policy.lease_duration,
        )

    def is_live_at(self, now: datetime) -> bool:
        return self.status is LeaseStatus.ACTIVE and now <= self.expires_at

    def extend(self, now: datetime, policy: RunnerTimingPolicy) -> None:
        """期限を、受信時刻から lease_duration だけ延長する。期限を過ぎていたら延長せず LeaseExpired。"""
        self._require_active("extend")
        if now > self.expires_at:
            raise LeaseExpired(self.lease_id)
        self.expires_at = now + policy.lease_duration
        self.last_extended_at = now

    def expire(self, now: datetime) -> None:
        """延長されずに期限を過ぎたリースを、リース切れとして記録する。"""
        self._require_active("expire")
        if now <= self.expires_at:
            raise InvalidLeaseTransition(self.status.value, "expire(期限前)")
        self.status = LeaseStatus.EXPIRED

    def end(self) -> None:
        """ジョブが終了状態になったリースを終了とする。"""
        self._require_active("end")
        self.status = LeaseStatus.ENDED

    def _require_active(self, operation: str) -> None:
        if self.status is not LeaseStatus.ACTIVE:
            raise InvalidLeaseTransition(self.status.value, operation)
