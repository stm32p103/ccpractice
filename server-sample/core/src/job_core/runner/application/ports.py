"""runner のポート(contracts/ports.md)。振る舞いの約束は contracts/ports.md を正とする。

RunnerUnitOfWork は 001 の UnitOfWork を拡張し、追加の 4 つのリポジトリにも同じ約束
(すべて確定するか何も確定しない、version の衝突で ConcurrencyConflict)を適用する(research.md R5)。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from job_core.job.application.ports import CoreDependencies, UnitOfWork
from job_core.runner.domain.allowlist import CapabilityAllowlist
from job_core.runner.domain.lease import Lease
from job_core.runner.domain.runner import Runner
from job_core.runner.domain.token import RunnerToken
from job_core.runner.domain.values import Capabilities, RunnerTimingPolicy, TokenHash
from job_core.shared.ids import JobId, RunnerId
from job_core.shared.ports import SecretGenerator

__all__ = [
    "CapabilityAllowlistRepository",
    "LeaseRepository",
    "RunnerCatalog",
    "RunnerDependencies",
    "RunnerRepository",
    "RunnerTokenRepository",
    "RunnerUnitOfWork",
    "RunnerUnitOfWorkFactory",
]


class RunnerRepository(Protocol):
    def get(self, runner_id: RunnerId) -> Runner | None:
        """削除済みも返す。"""
        ...

    def add(self, runner: Runner) -> None:
        """削除されていない同名があれば DuplicateRunnerName(コミット時の検出でもよい)。"""
        ...

    def save(self, runner: Runner) -> None: ...

    def list_active(self) -> list[Runner]:
        """削除されていないもの、名前の順。"""
        ...


class LeaseRepository(Protocol):
    def add(self, lease: Lease) -> None: ...
    def save(self, lease: Lease) -> None: ...

    def find_active_by_runner(self, runner_id: RunnerId) -> Lease | None:
        """status = ACTIVE(期限は問わない)。"""
        ...

    def find_active_by_job(self, job_id: JobId) -> Lease | None: ...

    def list_active_expired_before(self, now: datetime) -> list[Lease]:
        """status = ACTIVE かつ expires_at < now。"""
        ...

    def list_active(self) -> list[Lease]: ...


class RunnerTokenRepository(Protocol):
    def add(self, token: RunnerToken) -> None: ...
    def save(self, token: RunnerToken) -> None: ...
    def find_by_hash(self, token_hash: TokenHash) -> RunnerToken | None: ...
    def find_valid_by_runner(self, runner_id: RunnerId) -> RunnerToken | None: ...


class CapabilityAllowlistRepository(Protocol):
    def get(self) -> CapabilityAllowlist:
        """なければ空の許可リスト。"""
        ...

    def save(self, allowlist: CapabilityAllowlist) -> None: ...


class RunnerUnitOfWork(UnitOfWork, Protocol):
    @property
    def runners(self) -> RunnerRepository: ...
    @property
    def leases(self) -> LeaseRepository: ...
    @property
    def tokens(self) -> RunnerTokenRepository: ...
    @property
    def allowlist(self) -> CapabilityAllowlistRepository: ...


RunnerUnitOfWorkFactory = Callable[[], RunnerUnitOfWork]


class RunnerCatalog(Protocol):
    """判定用の読み取り。副作用を持たない。最後に確定した登録・削除を反映する。"""

    def active_capabilities(self) -> list[tuple[RunnerId, Capabilities]]:
        """削除されていないもの。"""
        ...

    def capabilities_of(self, runner_id: RunnerId) -> Capabilities | None:
        """削除済み・未知は None。"""
        ...


@dataclass(frozen=True, kw_only=True)
class RunnerDependencies(CoreDependencies):
    """runner のユースケースが使うポートの束。001 の CoreDependencies の項目に、追加のポートを加える。

    uow_factory は RunnerUnitOfWork を返すこと(001 のユースケースも、そのままこの UoW の上で動く)。
    型は 001 の UnitOfWorkFactory のままとし、runner のユースケースは
    uow_support.run_in_runner_uow で RunnerUnitOfWork として使う。
    """

    catalog: RunnerCatalog
    secrets: SecretGenerator
    timing: RunnerTimingPolicy = field(default_factory=RunnerTimingPolicy)
