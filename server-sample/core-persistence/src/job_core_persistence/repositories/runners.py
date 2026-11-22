"""ランナー・リース・トークン・許可リストのリポジトリと、判定用の読み取り(002 contracts/ports.md)。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from job_core.runner.domain.allowlist import CapabilityAllowlist
from job_core.runner.domain.errors import DuplicateRunnerName
from job_core.runner.domain.lease import Lease, LeaseStatus
from job_core.runner.domain.runner import Runner
from job_core.runner.domain.token import RunnerToken
from job_core.runner.domain.values import Capabilities, TokenHash
from job_core.shared.ids import JobId, RunnerId

from ..codec import decode
from ..models import capability_allowlist, leases, runner_tokens, runners
from ..tracking import Singleton, Tracked


class SqlRunnerRepository:
    def __init__(self, engine: Engine) -> None:
        self.tracked = Tracked[Runner](
            engine,
            runners,
            "runner_id",
            Runner,
            lambda r: {"name": r.name.value, "deleted": r.deleted_at is not None},
            "ランナー",
        )

    def get(self, runner_id: RunnerId) -> Runner | None:
        return self.tracked.load(runner_id)

    def add(self, runner: Runner) -> None:
        taken = self.tracked.query(
            sa.and_(runners.c.name == runner.name.value, runners.c.deleted.is_(False)),
            lambda r: r.deleted_at is None and r.name == runner.name,
            track=False,
        )
        if taken:
            raise DuplicateRunnerName(runner.name.value)
        self.tracked.add(runner.runner_id, runner)

    def save(self, runner: Runner) -> None:
        self.tracked.save(runner.runner_id, runner)

    def list_active(self) -> list[Runner]:
        found = self.tracked.query(runners.c.deleted.is_(False), lambda r: r.deleted_at is None)
        return sorted(found, key=lambda r: (r.name.value, r.runner_id))


def _lease_row(lease: Lease) -> dict[str, Any]:
    return {
        "job_id": lease.job_id,
        "runner_id": lease.runner_id,
        "status": lease.status.value,
        "expires_at": lease.expires_at,
    }


class SqlLeaseRepository:
    def __init__(self, engine: Engine) -> None:
        self.tracked = Tracked[Lease](engine, leases, "lease_id", Lease, _lease_row, "リース")

    def add(self, lease: Lease) -> None:
        self.tracked.add(lease.lease_id, lease)

    def save(self, lease: Lease) -> None:
        self.tracked.save(lease.lease_id, lease)

    def _active(self, where: sa.ColumnElement[bool], predicate: Any) -> list[Lease]:
        found = self.tracked.query(
            sa.and_(leases.c.status == LeaseStatus.ACTIVE.value, where),
            lambda lease: lease.status is LeaseStatus.ACTIVE and predicate(lease),
        )
        return sorted(found, key=lambda lease: lease.lease_id)

    def find_active_by_runner(self, runner_id: RunnerId) -> Lease | None:
        found = self._active(leases.c.runner_id == runner_id, lambda lease: lease.runner_id == runner_id)
        return found[0] if found else None

    def find_active_by_job(self, job_id: JobId) -> Lease | None:
        found = self._active(leases.c.job_id == job_id, lambda lease: lease.job_id == job_id)
        return found[0] if found else None

    def list_active_expired_before(self, now: datetime) -> list[Lease]:
        return self._active(leases.c.expires_at < now, lambda lease: lease.expires_at < now)

    def list_active(self) -> list[Lease]:
        return self._active(sa.true(), lambda lease: True)


class SqlRunnerTokenRepository:
    def __init__(self, engine: Engine) -> None:
        self.tracked = Tracked[RunnerToken](
            engine,
            runner_tokens,
            "token_id",
            RunnerToken,
            lambda t: {"runner_id": t.runner_id, "token_hash": t.token_hash.value, "revoked": t.is_revoked},
            "トークン",
        )

    def add(self, token: RunnerToken) -> None:
        self.tracked.add(token.token_id, token)

    def save(self, token: RunnerToken) -> None:
        self.tracked.save(token.token_id, token)

    def find_by_hash(self, token_hash: TokenHash) -> RunnerToken | None:
        found = self.tracked.query(runner_tokens.c.token_hash == token_hash.value, lambda t: t.token_hash == token_hash)
        return found[0] if found else None

    def find_valid_by_runner(self, runner_id: RunnerId) -> RunnerToken | None:
        found = self.tracked.query(
            sa.and_(runner_tokens.c.runner_id == runner_id, runner_tokens.c.revoked.is_(False)),
            lambda t: t.runner_id == runner_id and not t.is_revoked,
        )
        return found[0] if found else None


class SqlAllowlistRepository:
    def __init__(self, engine: Engine) -> None:
        self.singleton = Singleton[CapabilityAllowlist](
            engine, capability_allowlist, "id", "default", CapabilityAllowlist, CapabilityAllowlist, "許可リスト"
        )

    def get(self) -> CapabilityAllowlist:
        return self.singleton.get()

    def save(self, allowlist: CapabilityAllowlist) -> None:
        self.singleton.save(allowlist)


class SqlRunnerCatalog:
    """判定用の読み取り。確定した状態だけを読み、副作用を持たない。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def active_capabilities(self) -> list[tuple[RunnerId, Capabilities]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(runners.c.doc).where(runners.c.deleted.is_(False)).order_by(runners.c.runner_id)
            ).all()
        runners_ = [decode(Runner, r.doc) for r in rows]
        return [(r.runner_id, r.capabilities) for r in runners_]

    def capabilities_of(self, runner_id: RunnerId) -> Capabilities | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(runners.c.doc).where(runners.c.runner_id == runner_id, runners.c.deleted.is_(False))
            ).first()
        return None if row is None else decode(Runner, row.doc).capabilities
