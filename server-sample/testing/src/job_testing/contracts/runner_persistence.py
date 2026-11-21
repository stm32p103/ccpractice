"""runner のポートの契約テスト(002 contracts/ports.md「契約テストの一覧」。data-model.md §8 の不変条件 1・3・4 を含む)。

使い方: テストのクラスでこれらを継承し、次のフィクスチャを定義する。
- `new_uow`: 引数なしで、新しい RunnerUnitOfWork を返す関数(永続化は空の状態から始めること)
- `catalog`(RunnerCatalogContract だけ): 同じ永続化を読む RunnerCatalog
core-persistence(実アダプタ)も同じクラスを継承して実行する。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from job_core.job.domain.errors import ConcurrencyConflict
from job_core.job.domain.values import Reason
from job_core.runner.application.ports import RunnerCatalog, RunnerUnitOfWork
from job_core.runner.domain.errors import DuplicateRunnerName
from job_core.runner.domain.lease import Lease, LeaseStatus
from job_core.runner.domain.runner import Connectivity, Runner
from job_core.runner.domain.token import RunnerToken, hash_token
from job_core.runner.domain.values import (
    Capabilities,
    FaultDescription,
    RunnerName,
    RunnerTimingPolicy,
    ValueKind,
)
from job_core.shared.ids import JobId, RunnerId, SubjectId

from ._builders import make_job

NewRunnerUow = Callable[[], RunnerUnitOfWork]

T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
POLICY = RunnerTimingPolicy()


def make_runner(runner_id: str, name: str | None = None, at: datetime = T0) -> Runner:
    return Runner.create(RunnerId(runner_id), RunnerName(name or f"name-{runner_id}"), at)


def make_lease(lease_id: str, job_id: str, runner_id: str, at: datetime = T0) -> Lease:
    return Lease.grant(lease_id=lease_id, job_id=JobId(job_id), runner_id=RunnerId(runner_id), now=at, policy=POLICY)


def make_token(token_id: str, runner_id: str, value: str | None = None, at: datetime = T0) -> RunnerToken:
    return RunnerToken.issue(
        token_id=token_id, runner_id=RunnerId(runner_id), token_hash=hash_token(value or f"rt_{token_id}"), at=at
    )


def commit(new_uow: NewRunnerUow, action: Callable[[RunnerUnitOfWork], None]) -> None:
    with new_uow() as uow:
        action(uow)
        uow.commit()


# ---------------------------------------------------------------------- UnitOfWork


class RunnerUnitOfWorkContract:
    def test_commit_makes_all_repositories_visible_together(self, new_uow: NewRunnerUow) -> None:
        def write(uow: RunnerUnitOfWork) -> None:
            uow.runners.add(make_runner("R1"))
            uow.leases.add(make_lease("L1", "j1", "R1"))
            uow.tokens.add(make_token("T1", "R1"))
            allowlist = uow.allowlist.get()
            allowlist.replace({"k1": "single"})
            uow.allowlist.save(allowlist)
            uow.jobs.add(make_job("j1"))

        commit(new_uow, write)
        with new_uow() as uow:
            assert uow.runners.get(RunnerId("R1")) is not None
            assert uow.leases.find_active_by_job(JobId("j1")) is not None
            assert uow.tokens.find_valid_by_runner(RunnerId("R1")) is not None
            assert dict(uow.allowlist.get().entries) == {"k1": ValueKind.SINGLE}
            assert uow.jobs.get(JobId("j1")) is not None

    def test_uncommitted_changes_are_discarded(self, new_uow: NewRunnerUow) -> None:
        with new_uow() as uow:
            uow.runners.add(make_runner("R1"))
            uow.leases.add(make_lease("L1", "j1", "R1"))
            uow.tokens.add(make_token("T1", "R1"))
            allowlist = uow.allowlist.get()
            allowlist.replace({"k1": "single"})
            uow.allowlist.save(allowlist)
        with new_uow() as uow:
            assert uow.runners.get(RunnerId("R1")) is None
            assert uow.leases.list_active() == []
            assert uow.tokens.find_valid_by_runner(RunnerId("R1")) is None
            assert dict(uow.allowlist.get().entries) == {}

    def test_exception_discards_changes(self, new_uow: NewRunnerUow) -> None:
        with pytest.raises(RuntimeError), new_uow() as uow:
            uow.runners.add(make_runner("R1"))
            raise RuntimeError("本体の失敗")
        with new_uow() as uow:
            assert uow.runners.get(RunnerId("R1")) is None

    def test_pending_changes_are_visible_inside_the_same_uow(self, new_uow: NewRunnerUow) -> None:
        with new_uow() as uow:
            uow.runners.add(make_runner("R1"))
            uow.tokens.add(make_token("T1", "R1"))
            assert uow.runners.get(RunnerId("R1")) is not None
            assert uow.tokens.find_valid_by_runner(RunnerId("R1")) is not None

    def test_concurrent_update_of_runner_conflicts_and_rolls_back_everything(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.runners.add(make_runner("R1")))
        first = new_uow()
        second = new_uow()
        with first, second:
            r1 = first.runners.get(RunnerId("R1"))
            r2 = second.runners.get(RunnerId("R1"))
            assert r1 is not None and r2 is not None
            r1.report_fault(FaultDescription("e1"), T0)
            first.runners.save(r1)
            first.commit()
            r2.set_maintenance(SubjectId("admin"), T0, Reason("m"))
            second.runners.save(r2)
            second.leases.add(make_lease("L-lost", "j9", "R1"))  # 失敗した UoW の他の変更も確定しない
            with pytest.raises(ConcurrencyConflict):
                second.commit()
        with new_uow() as uow:
            stored = uow.runners.get(RunnerId("R1"))
            assert stored is not None and stored.fault is not None and stored.maintenance is None
            assert uow.leases.list_active() == []

    def test_concurrent_update_of_allowlist_conflicts(self, new_uow: NewRunnerUow) -> None:
        first = new_uow()
        second = new_uow()
        with first, second:
            a = first.allowlist.get()
            b = second.allowlist.get()
            a.replace({"k1": "single"})
            first.allowlist.save(a)
            first.commit()
            b.replace({"k2": "set"})
            second.allowlist.save(b)
            with pytest.raises(ConcurrencyConflict):
                second.commit()
        with new_uow() as uow:
            assert dict(uow.allowlist.get().entries) == {"k1": ValueKind.SINGLE}

    def test_concurrent_update_of_lease_conflicts(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.leases.add(make_lease("L1", "j1", "R1")))
        first = new_uow()
        second = new_uow()
        with first, second:
            a = first.leases.find_active_by_job(JobId("j1"))
            b = second.leases.find_active_by_job(JobId("j1"))
            assert a is not None and b is not None
            a.extend(T0 + timedelta(seconds=10), POLICY)
            first.leases.save(a)
            first.commit()
            b.end()
            second.leases.save(b)
            with pytest.raises(ConcurrencyConflict):
                second.commit()

    def test_version_is_advanced_only_when_something_changed(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.runners.add(make_runner("R1")))
        with new_uow() as uow:
            runner = uow.runners.get(RunnerId("R1"))
            assert runner is not None
            version = runner.version
            uow.commit()  # 変更なし
        with new_uow() as uow:
            runner = uow.runners.get(RunnerId("R1"))
            assert runner is not None and runner.version == version


# ---------------------------------------------------------------------- RunnerRepository


class RunnerRepositoryContract:
    def test_roundtrip_preserves_every_field(self, new_uow: NewRunnerUow) -> None:
        runner = make_runner("R1", "r-a")
        runner.register(Capabilities.of({"k1": "a", "set1": ["y", "x"], "e": []}), T0 + timedelta(seconds=5))
        runner.touch(T0 + timedelta(seconds=9))
        runner.mark_connectivity(Connectivity.ONLINE)
        runner.set_maintenance(SubjectId("admin"), T0, Reason("保守"))
        runner.report_fault(FaultDescription("e1"), T0 + timedelta(seconds=7))
        commit(new_uow, lambda uow: uow.runners.add(runner))
        with new_uow() as uow:
            stored = uow.runners.get(RunnerId("R1"))
            assert stored is not None
            assert stored.name == RunnerName("r-a")
            assert stored.capabilities == Capabilities.of({"k1": "a", "set1": ["x", "y"], "e": []})
            assert stored.capabilities.to_json() == {"e": [], "k1": "a", "set1": ["x", "y"]}  # 1 つの値と集合の区別
            assert stored.registered_at == T0 + timedelta(seconds=5)
            assert stored.last_seen_at == T0 + timedelta(seconds=9)
            assert stored.recorded_connectivity is Connectivity.ONLINE
            assert stored.maintenance is not None and stored.maintenance.reason == Reason("保守")
            assert stored.maintenance.set_by == SubjectId("admin")
            assert stored.fault is not None and stored.fault.description == FaultDescription("e1")
            assert stored.fault.reported_at == T0 + timedelta(seconds=7)
            assert stored.deleted_at is None
            assert stored.created_at == T0

    def test_unknown_runner_is_none_and_deleted_runner_is_returned_by_get(self, new_uow: NewRunnerUow) -> None:
        with new_uow() as uow:
            assert uow.runners.get(RunnerId("nobody")) is None
        commit(new_uow, lambda uow: uow.runners.add(make_runner("R1")))
        with new_uow() as uow:
            runner = uow.runners.get(RunnerId("R1"))
            assert runner is not None
            runner.delete(T0 + timedelta(seconds=1))
            uow.runners.save(runner)
            uow.commit()
        with new_uow() as uow:
            stored = uow.runners.get(RunnerId("R1"))
            assert stored is not None and stored.deleted_at == T0 + timedelta(seconds=1)
            assert uow.runners.list_active() == []

    def test_list_active_is_ordered_by_name_and_excludes_deleted(self, new_uow: NewRunnerUow) -> None:
        def write(uow: RunnerUnitOfWork) -> None:
            for runner_id, name in (("R1", "b"), ("R2", "a"), ("R3", "c")):
                uow.runners.add(make_runner(runner_id, name))

        commit(new_uow, write)
        with new_uow() as uow:
            gone = uow.runners.get(RunnerId("R3"))
            assert gone is not None
            gone.delete(T0)
            uow.runners.save(gone)
            uow.commit()
        with new_uow() as uow:
            assert [r.name.value for r in uow.runners.list_active()] == ["a", "b"]

    def test_duplicate_active_name_is_rejected(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.runners.add(make_runner("R1", "same")))
        with pytest.raises((DuplicateRunnerName, ConcurrencyConflict)), new_uow() as uow:
            uow.runners.add(make_runner("R2", "same"))
            uow.commit()  # 追加の時点、またはコミットの時点で拒否される
        with new_uow() as uow:
            assert uow.runners.get(RunnerId("R2")) is None

    def test_concurrent_adds_of_same_name_let_only_one_commit(self, new_uow: NewRunnerUow) -> None:
        first = new_uow()
        second = new_uow()
        with first, second:
            first.runners.add(make_runner("R1", "same"))
            second.runners.add(make_runner("R2", "same"))
            first.commit()
            with pytest.raises((DuplicateRunnerName, ConcurrencyConflict)):
                second.commit()
        with new_uow() as uow:
            assert [r.runner_id for r in uow.runners.list_active()] == ["R1"]

    def test_name_can_be_reused_after_deletion(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.runners.add(make_runner("R1", "same")))
        with new_uow() as uow:
            old = uow.runners.get(RunnerId("R1"))
            assert old is not None
            old.delete(T0)
            uow.runners.save(old)
            uow.commit()
        commit(new_uow, lambda uow: uow.runners.add(make_runner("R2", "same")))
        with new_uow() as uow:
            assert [r.runner_id for r in uow.runners.list_active()] == ["R2"]
            assert uow.runners.get(RunnerId("R1")) is not None  # 削除済みの識別子と名前は残る


# ---------------------------------------------------------------------- LeaseRepository


class LeaseRepositoryContract:
    def test_roundtrip_and_finders(self, new_uow: NewRunnerUow) -> None:
        lease = make_lease("L1", "j1", "R1")
        lease.extend(T0 + timedelta(seconds=30), POLICY)
        commit(new_uow, lambda uow: uow.leases.add(lease))
        with new_uow() as uow:
            by_runner = uow.leases.find_active_by_runner(RunnerId("R1"))
            by_job = uow.leases.find_active_by_job(JobId("j1"))
            assert by_runner is not None and by_job is not None
            assert by_runner.lease_id == by_job.lease_id == "L1"
            assert by_runner.expires_at == T0 + timedelta(seconds=30) + POLICY.lease_duration
            assert by_runner.last_extended_at == T0 + timedelta(seconds=30)
            assert by_runner.granted_at == T0
            assert by_runner.status is LeaseStatus.ACTIVE
            assert uow.leases.find_active_by_runner(RunnerId("other")) is None
            assert uow.leases.find_active_by_job(JobId("other")) is None

    def test_ended_and_expired_leases_are_not_active(self, new_uow: NewRunnerUow) -> None:
        def write(uow: RunnerUnitOfWork) -> None:
            uow.leases.add(make_lease("L1", "j1", "R1"))
            uow.leases.add(make_lease("L2", "j2", "R2"))

        commit(new_uow, write)
        with new_uow() as uow:
            ended = uow.leases.find_active_by_job(JobId("j1"))
            expired = uow.leases.find_active_by_job(JobId("j2"))
            assert ended is not None and expired is not None
            ended.end()
            expired.expire(T0 + POLICY.lease_duration + timedelta(seconds=1))
            uow.leases.save(ended)
            uow.leases.save(expired)
            uow.commit()
        with new_uow() as uow:
            assert uow.leases.list_active() == []
            assert uow.leases.find_active_by_runner(RunnerId("R1")) is None
            assert uow.leases.list_active_expired_before(T0 + timedelta(days=1)) == []

    def test_list_active_expired_before_is_strict(self, new_uow: NewRunnerUow) -> None:
        def write(uow: RunnerUnitOfWork) -> None:
            uow.leases.add(make_lease("L1", "j1", "R1", T0))
            uow.leases.add(make_lease("L2", "j2", "R2", T0 + timedelta(minutes=10)))

        commit(new_uow, write)
        deadline = T0 + POLICY.lease_duration
        with new_uow() as uow:
            assert uow.leases.list_active_expired_before(deadline) == []  # 期限ちょうどは含まない
            late = uow.leases.list_active_expired_before(deadline + timedelta(microseconds=1))
            assert [lease.lease_id for lease in late] == ["L1"]
            assert [lease.lease_id for lease in uow.leases.list_active()] == ["L1", "L2"]

    def test_only_one_active_lease_per_job(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.leases.add(make_lease("L1", "j1", "R1")))
        with pytest.raises(ConcurrencyConflict), new_uow() as uow:
            uow.leases.add(make_lease("L2", "j1", "R2"))
            uow.commit()
        with new_uow() as uow:
            assert [lease.lease_id for lease in uow.leases.list_active()] == ["L1"]

    def test_only_one_active_lease_per_runner(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.leases.add(make_lease("L1", "j1", "R1")))
        with pytest.raises(ConcurrencyConflict), new_uow() as uow:
            uow.leases.add(make_lease("L2", "j2", "R1"))
            uow.commit()

    def test_new_lease_is_allowed_after_the_old_one_ended_in_the_same_uow(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.leases.add(make_lease("L1", "j1", "R1")))
        with new_uow() as uow:
            old = uow.leases.find_active_by_runner(RunnerId("R1"))
            assert old is not None
            old.end()
            uow.leases.save(old)
            uow.leases.add(make_lease("L2", "j2", "R1"))
            uow.commit()
        with new_uow() as uow:
            active = uow.leases.find_active_by_runner(RunnerId("R1"))
            assert active is not None and active.lease_id == "L2"


# ---------------------------------------------------------------------- RunnerTokenRepository


class RunnerTokenRepositoryContract:
    def test_find_by_hash_and_valid_by_runner(self, new_uow: NewRunnerUow) -> None:
        token = make_token("T1", "R1", "rt_value-1")
        commit(new_uow, lambda uow: uow.tokens.add(token))
        with new_uow() as uow:
            found = uow.tokens.find_by_hash(hash_token("rt_value-1"))
            assert found is not None and found.token_id == "T1" and found.runner_id == "R1"
            assert uow.tokens.find_by_hash(hash_token("rt_other")) is None
            valid = uow.tokens.find_valid_by_runner(RunnerId("R1"))
            assert valid is not None and valid.token_id == "T1"
            assert uow.tokens.find_valid_by_runner(RunnerId("R2")) is None

    def test_revoked_token_is_found_by_hash_but_not_valid(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.tokens.add(make_token("T1", "R1", "rt_value-1")))
        with new_uow() as uow:
            token = uow.tokens.find_valid_by_runner(RunnerId("R1"))
            assert token is not None
            token.revoke(T0 + timedelta(seconds=3))
            uow.tokens.save(token)
            uow.commit()
        with new_uow() as uow:
            found = uow.tokens.find_by_hash(hash_token("rt_value-1"))
            assert found is not None and found.revoked_at == T0 + timedelta(seconds=3)
            assert uow.tokens.find_valid_by_runner(RunnerId("R1")) is None

    def test_only_one_valid_token_per_runner(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.tokens.add(make_token("T1", "R1")))
        with pytest.raises(ConcurrencyConflict), new_uow() as uow:
            uow.tokens.add(make_token("T2", "R1"))
            uow.commit()
        with new_uow() as uow:
            valid = uow.tokens.find_valid_by_runner(RunnerId("R1"))
            assert valid is not None and valid.token_id == "T1"

    def test_reissue_in_one_uow_replaces_the_valid_token(self, new_uow: NewRunnerUow) -> None:
        commit(new_uow, lambda uow: uow.tokens.add(make_token("T1", "R1", "rt_old")))
        with new_uow() as uow:
            old = uow.tokens.find_valid_by_runner(RunnerId("R1"))
            assert old is not None
            old.revoke(T0)
            uow.tokens.save(old)
            uow.tokens.add(make_token("T2", "R1", "rt_new"))
            uow.commit()
        with new_uow() as uow:
            valid = uow.tokens.find_valid_by_runner(RunnerId("R1"))
            assert valid is not None and valid.token_id == "T2"
            assert uow.tokens.find_by_hash(hash_token("rt_old")) is not None

    def test_the_port_never_holds_the_token_value(self, new_uow: NewRunnerUow) -> None:
        value = "rt_SECRET-VALUE-9999"
        commit(new_uow, lambda uow: uow.tokens.add(make_token("T1", "R1", value)))
        with new_uow() as uow:
            stored = uow.tokens.find_valid_by_runner(RunnerId("R1"))
            assert stored is not None
            assert value not in repr(stored)
            assert not any(value == getattr(stored, name, None) for name in vars(stored))


# ---------------------------------------------------------------------- CapabilityAllowlistRepository


class CapabilityAllowlistRepositoryContract:
    def test_default_is_empty(self, new_uow: NewRunnerUow) -> None:
        with new_uow() as uow:
            allowlist = uow.allowlist.get()
            assert dict(allowlist.entries) == {}

    def test_save_and_restore(self, new_uow: NewRunnerUow) -> None:
        def write(uow: RunnerUnitOfWork) -> None:
            allowlist = uow.allowlist.get()
            allowlist.replace({"k1": "single", "set1": "set"})
            uow.allowlist.save(allowlist)

        commit(new_uow, write)
        with new_uow() as uow:
            allowlist = uow.allowlist.get()
            assert dict(allowlist.entries) == {"k1": ValueKind.SINGLE, "set1": ValueKind.SET}
            assert allowlist.version >= 1


# ---------------------------------------------------------------------- RunnerCatalog


class RunnerCatalogContract:
    def test_reflects_committed_registrations_and_excludes_deleted(
        self, new_uow: NewRunnerUow, catalog: RunnerCatalog
    ) -> None:
        def write(uow: RunnerUnitOfWork) -> None:
            for runner_id in ("R1", "R2"):
                runner = make_runner(runner_id)
                runner.register(Capabilities.of({"k1": runner_id, "set1": ["x"]}), T0)
                uow.runners.add(runner)

        commit(new_uow, write)
        listed = dict(catalog.active_capabilities())
        assert set(listed) == {"R1", "R2"}
        assert listed[RunnerId("R1")] == Capabilities.of({"k1": "R1", "set1": ["x"]})
        assert catalog.capabilities_of(RunnerId("R2")) == Capabilities.of({"k1": "R2", "set1": ["x"]})
        with new_uow() as uow:
            runner = uow.runners.get(RunnerId("R2"))
            assert runner is not None
            runner.delete(T0)
            uow.runners.save(runner)
            uow.commit()
        assert set(dict(catalog.active_capabilities())) == {"R1"}
        assert catalog.capabilities_of(RunnerId("R2")) is None
        assert catalog.capabilities_of(RunnerId("nobody")) is None

    def test_has_no_side_effects_and_ignores_uncommitted_changes(
        self, new_uow: NewRunnerUow, catalog: RunnerCatalog
    ) -> None:
        with new_uow() as uow:
            runner = make_runner("R1")
            runner.register(Capabilities.of({"k1": "a"}), T0)
            uow.runners.add(runner)
            assert catalog.active_capabilities() == []  # 未確定の変更は見えない
            uow.commit()
        first = catalog.active_capabilities()
        second = catalog.active_capabilities()
        assert first == second and len(first) == 1
        with new_uow() as uow:
            stored = uow.runners.get(RunnerId("R1"))
            assert stored is not None and stored.version == 1  # 読み取りがバージョンを進めない
