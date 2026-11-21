"""Runner 集約の単体テスト(data-model.md §2。FR-010 の優先順の全組み合わせ)。"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from job_core.job.domain.values import Reason
from job_core.runner.domain.errors import (
    AlreadyInMaintenance,
    NotInMaintenance,
    RunnerDeleted,
    RunnerNotRegistered,
)
from job_core.runner.domain.runner import Connectivity, Runner, RunnerState
from job_core.runner.domain.values import Capabilities, FaultDescription, RunnerName, RunnerTimingPolicy
from job_core.shared.ids import RunnerId, SubjectId

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
POLICY = RunnerTimingPolicy()
ADMIN = SubjectId("admin")


def new_runner() -> Runner:
    return Runner.create(RunnerId("R1"), RunnerName("r-a"), T0)


def registered_runner(at: datetime = T0) -> Runner:
    runner = new_runner()
    runner.register(Capabilities.of({"k1": "a"}), at)
    return runner


class TestCreate:
    def test_initial_values(self) -> None:
        runner = new_runner()
        assert runner.capabilities == Capabilities()
        assert runner.registered_at is None
        assert runner.last_seen_at is None
        assert runner.recorded_connectivity is Connectivity.OFFLINE
        assert runner.maintenance is None
        assert runner.fault is None
        assert runner.state_at(T0, POLICY) is RunnerState.OFFLINE

    def test_requires_id(self) -> None:
        with pytest.raises(ValueError):
            Runner.create(RunnerId(" "), RunnerName("x"), T0)


class TestStateDerivation:
    @pytest.mark.parametrize(
        ("deleted", "maintenance", "fault", "registered", "elapsed_seconds"),
        list(
            itertools.product(
                [False, True],
                [False, True],
                [False, True],
                [False, True],
                [0, 90, 91],  # offline_after(90 秒)の前、ちょうど、後
            )
        ),
    )
    def test_priority_order(
        self, deleted: bool, maintenance: bool, fault: bool, registered: bool, elapsed_seconds: int
    ) -> None:
        runner = new_runner()
        if registered:
            runner.register(Capabilities(), T0)
        if maintenance:
            runner.set_maintenance(ADMIN, T0, None)
        if fault:
            runner.report_fault(FaultDescription("e1"), T0)
        if deleted:
            runner.delete(T0)
        now = T0 + timedelta(seconds=elapsed_seconds)
        stale = elapsed_seconds > 90

        if deleted:
            expected = RunnerState.DELETED
        elif maintenance:
            expected = RunnerState.MAINTENANCE
        elif fault:
            expected = RunnerState.FAULT
        elif not registered or stale:
            expected = RunnerState.OFFLINE
        else:
            expected = RunnerState.ONLINE
        assert runner.state_at(now, POLICY) is expected

    def test_connectivity_is_independent_of_maintenance_and_fault(self) -> None:
        runner = registered_runner()
        runner.set_maintenance(ADMIN, T0, None)
        runner.report_fault(FaultDescription("e1"), T0)
        assert runner.connectivity_at(T0, POLICY) is Connectivity.ONLINE
        assert runner.connectivity_at(T0 + timedelta(seconds=91), POLICY) is Connectivity.OFFLINE

    def test_exactly_offline_after_is_still_online(self) -> None:
        runner = registered_runner()
        assert runner.state_at(T0 + timedelta(seconds=90), POLICY) is RunnerState.ONLINE
        assert runner.state_at(T0 + timedelta(seconds=90, microseconds=1), POLICY) is RunnerState.OFFLINE


class TestRegisterAndTouch:
    def test_register_replaces_capabilities_entirely(self) -> None:
        runner = registered_runner()
        later = T0 + timedelta(minutes=5)
        runner.register(Capabilities.of({"set1": ["x"]}), later)
        assert runner.capabilities == Capabilities.of({"set1": ["x"]})
        assert runner.capabilities.get("k1") is None
        assert runner.registered_at == later
        assert runner.last_seen_at == later

    def test_touch_requires_registration(self) -> None:
        with pytest.raises(RunnerNotRegistered):
            new_runner().touch(T0)

    def test_touch_updates_last_seen_only(self) -> None:
        runner = registered_runner()
        later = T0 + timedelta(seconds=30)
        runner.touch(later)
        assert runner.last_seen_at == later
        assert runner.registered_at == T0

    def test_seen_does_not_require_registration(self) -> None:
        runner = new_runner()
        runner.seen(T0)
        assert runner.last_seen_at == T0
        assert runner.state_at(T0, POLICY) is RunnerState.OFFLINE

    def test_deleted_runner_rejects_everything(self) -> None:
        runner = registered_runner()
        runner.delete(T0)
        for action in (
            lambda: runner.register(Capabilities(), T0),
            lambda: runner.touch(T0),
            lambda: runner.seen(T0),
            lambda: runner.set_maintenance(ADMIN, T0, None),
            lambda: runner.report_fault(FaultDescription("e"), T0),
            lambda: runner.delete(T0),
        ):
            with pytest.raises(RunnerDeleted):
                action()

    def test_mark_connectivity_reports_change(self) -> None:
        runner = new_runner()
        assert runner.mark_connectivity(Connectivity.ONLINE) is True
        assert runner.mark_connectivity(Connectivity.ONLINE) is False
        assert runner.mark_connectivity(Connectivity.OFFLINE) is True


class TestMaintenance:
    def test_set_and_clear(self) -> None:
        runner = registered_runner()
        runner.set_maintenance(ADMIN, T0, Reason("保守"))
        assert runner.maintenance is not None
        assert runner.maintenance.reason == Reason("保守")
        with pytest.raises(AlreadyInMaintenance):
            runner.set_maintenance(ADMIN, T0, None)
        runner.clear_maintenance()
        assert runner.maintenance is None
        with pytest.raises(NotInMaintenance):
            runner.clear_maintenance()

    def test_not_released_by_heartbeat(self) -> None:
        runner = registered_runner()
        runner.set_maintenance(ADMIN, T0, None)
        runner.touch(T0 + timedelta(seconds=10))
        assert runner.state_at(T0 + timedelta(seconds=10), POLICY) is RunnerState.MAINTENANCE


class TestFault:
    def test_report_is_new_then_updates_description_only(self) -> None:
        runner = registered_runner()
        assert runner.report_fault(FaultDescription("e1"), T0) is True
        later = T0 + timedelta(seconds=40)
        assert runner.report_fault(FaultDescription("e2"), later) is False
        assert runner.fault is not None
        assert runner.fault.reported_at == T0
        assert runner.fault.updated_at == later
        assert runner.fault.description == FaultDescription("e2")

    def test_recovered_and_clear_report_change(self) -> None:
        runner = registered_runner()
        assert runner.report_recovered() is False
        runner.report_fault(FaultDescription("e1"), T0)
        assert runner.report_recovered() is True
        assert runner.fault is None
        runner.report_fault(FaultDescription("e1"), T0)
        assert runner.clear_fault() is True
        assert runner.clear_fault() is False

    def test_fault_is_not_released_by_going_offline_and_back(self) -> None:
        runner = registered_runner()
        runner.report_fault(FaultDescription("e1"), T0)
        later = T0 + timedelta(minutes=10)
        runner.touch(later)
        assert runner.state_at(later, POLICY) is RunnerState.FAULT

    def test_report_fault_does_not_change_registration(self) -> None:
        runner = new_runner()
        runner.report_fault(FaultDescription("e1"), T0)
        assert runner.registered_at is None
