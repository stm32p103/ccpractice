"""Runner 集約(data-model.md §2)。

項目: Runner.runner_id、.name、.created_at、.capabilities、.registered_at、.last_seen_at、
.recorded_connectivity、.maintenance、.fault、.deleted_at、.version。
状態(RunnerState)は保存せず、時刻と設定から導く(research.md R6。FR-010)。
状態の変更は、このメソッドだけで行う。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from job_core.job.domain.values import Reason
from job_core.shared.ids import RunnerId, SubjectId, is_valid_id

from .errors import AlreadyInMaintenance, NotInMaintenance, RunnerDeleted, RunnerNotRegistered
from .values import EMPTY_CAPABILITIES, Capabilities, FaultDescription, RunnerName, RunnerTimingPolicy


class RunnerState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"
    FAULT = "fault"
    DELETED = "deleted"


class Connectivity(StrEnum):
    """接続の状態。maintenance・異常とは独立に、生存通知の有無だけで決まる。"""

    ONLINE = "online"
    OFFLINE = "offline"


@dataclass(frozen=True)
class MaintenanceRecord:
    """maintenance の設定(設定者、日時、理由(任意))。"""

    set_by: SubjectId
    set_at: datetime
    reason: Reason | None = None


@dataclass(frozen=True)
class FaultRecord:
    """異常の申告(申告日時、説明、最終更新日時)。"""

    reported_at: datetime
    description: FaultDescription
    updated_at: datetime


@dataclass(eq=False)
class Runner:
    runner_id: RunnerId
    name: RunnerName
    created_at: datetime
    capabilities: Capabilities = EMPTY_CAPABILITIES
    registered_at: datetime | None = None
    last_seen_at: datetime | None = None
    recorded_connectivity: Connectivity = Connectivity.OFFLINE
    maintenance: MaintenanceRecord | None = None
    fault: FaultRecord | None = None
    deleted_at: datetime | None = None
    version: int = 0

    # ------------------------------------------------------------------ 生成

    @classmethod
    def create(cls, runner_id: RunnerId, name: RunnerName, at: datetime) -> Runner:
        if not is_valid_id(runner_id):
            raise ValueError("runner_id は空でない文字列でなければならない")
        return cls(runner_id=runner_id, name=name, created_at=at)

    # ------------------------------------------------------------------ 参照

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def state_at(self, now: datetime, policy: RunnerTimingPolicy) -> RunnerState:
        """FR-010 の優先順で状態を導く。"""
        if self.deleted_at is not None:
            return RunnerState.DELETED
        if self.maintenance is not None:
            return RunnerState.MAINTENANCE
        if self.fault is not None:
            return RunnerState.FAULT
        if self.connectivity_at(now, policy) is Connectivity.OFFLINE:
            return RunnerState.OFFLINE
        return RunnerState.ONLINE

    def connectivity_at(self, now: datetime, policy: RunnerTimingPolicy) -> Connectivity:
        """一度も登録していない、または最後の通信から offline_after を過ぎていれば OFFLINE。"""
        if self.registered_at is None or self.last_seen_at is None:
            return Connectivity.OFFLINE
        if now - self.last_seen_at > policy.offline_after:
            return Connectivity.OFFLINE
        return Connectivity.ONLINE

    # ------------------------------------------------------------------ 操作

    def register(self, capabilities: Capabilities, at: datetime) -> None:
        """起動時の登録。能力は申告の内容で丸ごと置き換わる(FR-003)。"""
        self._require_not_deleted()
        self.capabilities = capabilities
        self.registered_at = at
        self.last_seen_at = at

    def touch(self, at: datetime) -> None:
        """生存通知。登録済みのランナーだけが行える。"""
        self._require_not_deleted()
        if self.registered_at is None:
            raise RunnerNotRegistered(self.runner_id)
        self.last_seen_at = at

    def seen(self, at: datetime) -> None:
        """割り当ての要求・異常と回復の申告も、生存の証拠として最終応答時刻を更新する(spec 前提)。"""
        self._require_not_deleted()
        self.last_seen_at = at

    def mark_connectivity(self, connectivity: Connectivity) -> bool:
        """記録上の接続の状態を更新する。変化したかを返す。"""
        changed = self.recorded_connectivity is not connectivity
        self.recorded_connectivity = connectivity
        return changed

    def set_maintenance(self, by: SubjectId, at: datetime, reason: Reason | None) -> None:
        self._require_not_deleted()
        if self.maintenance is not None:
            raise AlreadyInMaintenance(self.runner_id)
        self.maintenance = MaintenanceRecord(set_by=by, set_at=at, reason=reason)

    def clear_maintenance(self) -> None:
        if self.maintenance is None:
            raise NotInMaintenance(self.runner_id)
        self.maintenance = None

    def report_fault(self, description: FaultDescription, at: datetime) -> bool:
        """異常の申告。既に異常なら説明と最終更新だけを変える。新たに異常になったときだけ真を返す。"""
        self._require_not_deleted()
        if self.fault is None:
            self.fault = FaultRecord(reported_at=at, description=description, updated_at=at)
            return True
        self.fault = FaultRecord(reported_at=self.fault.reported_at, description=description, updated_at=at)
        return False

    def report_recovered(self) -> bool:
        """回復の申告。異常がなければ何もしない。異常があったか(変化したか)を返す。"""
        return self.clear_fault()

    def clear_fault(self) -> bool:
        """異常の解除(手動の解除を含む)。異常がなければ何もしない。変化したかを返す。"""
        had_fault = self.fault is not None
        self.fault = None
        return had_fault

    def delete(self, at: datetime) -> None:
        self._require_not_deleted()
        self.deleted_at = at

    # ------------------------------------------------------------------ 内部

    def _require_not_deleted(self) -> None:
        if self.deleted_at is not None:
            raise RunnerDeleted(self.runner_id)
