"""runner のメモリ上のリポジトリ(contracts/ports.md「RunnerUnitOfWork」以下の約束の Fake)。

- 確定した状態は RunnerStoreState が持つ(InMemoryStore から共有される)。UoW は読み込んだ集約の複製を扱い、
  commit で version を比較して確定する(001 の Fake と同じ方式)。
- 一意性(削除されていない名前、1 件のジョブ・1 台のランナーの ACTIVE なリース、1 台のランナーの有効なトークン)は、
  commit のとき、この UoW の変更を重ねた状態で検査する。破られるときは ConcurrencyConflict で確定しない。
- RunnerCatalog は確定した状態だけを読む(副作用なし)。
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import datetime
from typing import Any

from job_core.job.domain.errors import ConcurrencyConflict
from job_core.runner.domain.allowlist import CapabilityAllowlist
from job_core.runner.domain.errors import DuplicateRunnerName
from job_core.runner.domain.lease import Lease, LeaseStatus
from job_core.runner.domain.runner import Runner
from job_core.runner.domain.token import RunnerToken
from job_core.runner.domain.values import Capabilities, TokenHash
from job_core.shared.ids import JobId, RunnerId


def _snapshot(obj: object) -> dict[str, Any]:
    """version 以外の全項目(集約が変更されたかの比較に使う)。"""
    return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj) if f.name != "version"}  # type: ignore[arg-type]


class RunnerStoreState:
    """確定した runner 側の状態。"""

    def __init__(self) -> None:
        self.runners: dict[str, Runner] = {}
        self.leases: dict[str, Lease] = {}
        self.tokens: dict[str, RunnerToken] = {}
        self.allowlist: CapabilityAllowlist = CapabilityAllowlist()


class _Tracked[T]:
    """1 種類の集約の、UoW ごとの読み込み・追加・保存の追跡。"""

    def __init__(self, committed: dict[str, T]) -> None:
        self.committed = committed
        self.pending: dict[str, T] = {}
        self.loaded_versions: dict[str, int] = {}
        self.new_keys: set[str] = set()

    def merged(self) -> dict[str, T]:
        merged = dict(self.committed)
        merged.update(self.pending)
        return merged

    def load(self, key: str) -> T | None:
        if key in self.pending:
            return self.pending[key]
        committed = self.committed.get(key)
        if committed is None:
            return None
        copied = copy.deepcopy(committed)
        self.loaded_versions[key] = copied.version  # type: ignore[attr-defined]
        self.pending[key] = copied
        return copied

    def add(self, key: str, obj: T) -> None:
        if key in self.merged():
            raise ValueError(f"{key} は既にある")
        self.pending[key] = obj
        self.new_keys.add(key)

    def save(self, key: str, obj: T) -> None:
        if key not in self.pending:
            raise ValueError("save は、この UoW で読み込んだか追加した集約にだけ使う")
        self.pending[key] = obj

    def check_versions(self, label: str) -> None:
        for key, loaded in self.loaded_versions.items():
            current = self.committed.get(key)
            if current is None or current.version != loaded:  # type: ignore[attr-defined]
                raise ConcurrencyConflict(f"{label} {key} が同時に更新された")
        for key in self.new_keys:
            if key in self.committed:
                raise ConcurrencyConflict(f"{label} {key} が同時に追加された")

    def apply(self) -> None:
        for key, obj in self.pending.items():
            if key in self.loaded_versions and _snapshot(self.committed[key]) == _snapshot(obj):
                continue
            obj.version += 1  # type: ignore[attr-defined]
            self.committed[key] = copy.deepcopy(obj)


class InMemoryRunnerRepository:
    def __init__(self, state: RunnerStoreState) -> None:
        self.tracked = _Tracked[Runner](state.runners)

    def get(self, runner_id: RunnerId) -> Runner | None:
        return self.tracked.load(runner_id)

    def add(self, runner: Runner) -> None:
        for existing in self.tracked.merged().values():
            if existing.deleted_at is None and existing.name == runner.name:
                raise DuplicateRunnerName(runner.name.value)
        self.tracked.add(runner.runner_id, runner)

    def save(self, runner: Runner) -> None:
        self.tracked.save(runner.runner_id, runner)

    def list_active(self) -> list[Runner]:
        keys = [k for k, r in self.tracked.merged().items() if r.deleted_at is None]
        loaded = [r for k in keys if (r := self.tracked.load(k)) is not None]
        return sorted(loaded, key=lambda r: (r.name.value, r.runner_id))

    def check(self) -> None:
        self.tracked.check_versions("ランナー")
        # 削除されていない名前の一意性(この UoW の変更を重ねた状態で検査する)
        names: dict[str, str] = {}
        for runner in self.tracked.merged().values():
            if runner.deleted_at is not None:
                continue
            owner = names.setdefault(runner.name.value, runner.runner_id)
            if owner != runner.runner_id:
                raise ConcurrencyConflict(f"ランナーの名前 {runner.name.value} が同時に使われた")


class InMemoryLeaseRepository:
    def __init__(self, state: RunnerStoreState) -> None:
        self.tracked = _Tracked[Lease](state.leases)

    def _active(self) -> list[Lease]:
        return [lease for lease in self.tracked.merged().values() if lease.status is LeaseStatus.ACTIVE]

    def _loaded(self, key: str) -> Lease | None:
        return self.tracked.load(key)

    def add(self, lease: Lease) -> None:
        self.tracked.add(lease.lease_id, lease)

    def save(self, lease: Lease) -> None:
        self.tracked.save(lease.lease_id, lease)

    def find_active_by_runner(self, runner_id: RunnerId) -> Lease | None:
        for lease in self._active():
            if lease.runner_id == runner_id:
                return self._loaded(lease.lease_id)
        return None

    def find_active_by_job(self, job_id: JobId) -> Lease | None:
        for lease in self._active():
            if lease.job_id == job_id:
                return self._loaded(lease.lease_id)
        return None

    def list_active_expired_before(self, now: datetime) -> list[Lease]:
        keys = [lease.lease_id for lease in self._active() if lease.expires_at < now]
        return sorted((x for k in keys if (x := self._loaded(k)) is not None), key=lambda x: x.lease_id)

    def list_active(self) -> list[Lease]:
        keys = [lease.lease_id for lease in self._active()]
        return sorted((x for k in keys if (x := self._loaded(k)) is not None), key=lambda x: x.lease_id)

    def check(self) -> None:
        self.tracked.check_versions("リース")
        by_job: dict[str, str] = {}
        by_runner: dict[str, str] = {}
        for lease in self._active():
            if by_job.setdefault(lease.job_id, lease.lease_id) != lease.lease_id:
                raise ConcurrencyConflict(f"ジョブ {lease.job_id} に ACTIVE なリースが 2 つできる")
            if by_runner.setdefault(lease.runner_id, lease.lease_id) != lease.lease_id:
                raise ConcurrencyConflict(f"ランナー {lease.runner_id} に ACTIVE なリースが 2 つできる")


class InMemoryRunnerTokenRepository:
    def __init__(self, state: RunnerStoreState) -> None:
        self.tracked = _Tracked[RunnerToken](state.tokens)

    def add(self, token: RunnerToken) -> None:
        self.tracked.add(token.token_id, token)

    def save(self, token: RunnerToken) -> None:
        self.tracked.save(token.token_id, token)

    def find_by_hash(self, token_hash: TokenHash) -> RunnerToken | None:
        for token in self.tracked.merged().values():
            if token.token_hash == token_hash:
                return self.tracked.load(token.token_id)
        return None

    def find_valid_by_runner(self, runner_id: RunnerId) -> RunnerToken | None:
        for token in self.tracked.merged().values():
            if token.runner_id == runner_id and not token.is_revoked:
                return self.tracked.load(token.token_id)
        return None

    def check(self) -> None:
        self.tracked.check_versions("トークン")
        valid: dict[str, str] = {}
        for token in self.tracked.merged().values():
            if token.is_revoked:
                continue
            if valid.setdefault(token.runner_id, token.token_id) != token.token_id:
                raise ConcurrencyConflict(f"ランナー {token.runner_id} に有効なトークンが 2 つできる")


class InMemoryAllowlistRepository:
    _KEY = "allowlist"

    def __init__(self, state: RunnerStoreState) -> None:
        self._state = state
        self.pending: CapabilityAllowlist | None = None
        self.loaded_version: int | None = None

    def get(self) -> CapabilityAllowlist:
        if self.pending is None:
            self.pending = copy.deepcopy(self._state.allowlist)
            self.loaded_version = self.pending.version
        return self.pending

    def save(self, allowlist: CapabilityAllowlist) -> None:
        if self.pending is None or allowlist is not self.pending:
            raise ValueError("save は、この UoW で get した許可リストにだけ使う")

    def check(self) -> None:
        if self.loaded_version is not None and self._state.allowlist.version != self.loaded_version:
            raise ConcurrencyConflict("許可リストが同時に更新された")

    def apply(self) -> None:
        if self.pending is not None and _snapshot(self.pending) != _snapshot(self._state.allowlist):
            self.pending.version += 1
            self._state.allowlist = copy.deepcopy(self.pending)


class RunnerRepositories:
    """1 つの UoW が持つ、runner のリポジトリの束と、commit の検査・反映。"""

    def __init__(self, state: RunnerStoreState) -> None:
        self.runners = InMemoryRunnerRepository(state)
        self.leases = InMemoryLeaseRepository(state)
        self.tokens = InMemoryRunnerTokenRepository(state)
        self.allowlist = InMemoryAllowlistRepository(state)

    def check(self) -> None:
        self.runners.check()
        self.leases.check()
        self.tokens.check()
        self.allowlist.check()

    def apply(self) -> None:
        self.runners.tracked.apply()
        self.leases.tracked.apply()
        self.tokens.tracked.apply()
        self.allowlist.apply()


class InMemoryRunnerCatalog:
    """判定用の読み取り。確定した状態だけを読み、副作用を持たない。"""

    def __init__(self, state: RunnerStoreState, lock: Any) -> None:
        self._state = state
        self._lock = lock

    def active_capabilities(self) -> list[tuple[RunnerId, Capabilities]]:
        with self._lock:
            active = [r for r in self._state.runners.values() if r.deleted_at is None]
            return [(r.runner_id, r.capabilities) for r in sorted(active, key=lambda r: r.runner_id)]

    def capabilities_of(self, runner_id: RunnerId) -> Capabilities | None:
        with self._lock:
            runner = self._state.runners.get(runner_id)
            if runner is None or runner.deleted_at is not None:
                return None
            return runner.capabilities
