"""ReplaceCapabilityAllowlist — 能力のキーの許可リストの設定(FR-004。research.md R12)。

既存のランナーの能力は変えない(次の登録から効く)。変更は監査ログ ALLOWLIST_CHANGE に残す。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.values import Reason

from ..audit import audited, make_runner_record
from ..authorization import authorize_manage
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import AllowlistView
from ..uow_support import run_in_runner_uow


class ReplaceCapabilityAllowlist:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, entries: Mapping[str, Any], reason: str | None = None) -> AllowlistView:
        deps = self._deps
        audited(deps, principal, AuditOperation.ALLOWLIST_CHANGE, None, lambda: authorize_manage(principal))
        why = Reason(reason).value if reason is not None else None

        def operate(uow: RunnerUnitOfWork) -> AllowlistView:
            allowlist = uow.allowlist.get()
            before = {key: kind.value for key, kind in sorted(allowlist.entries.items())}
            allowlist.replace(entries)
            uow.allowlist.save(allowlist)
            after = {key: kind.value for key, kind in sorted(allowlist.entries.items())}
            uow.audit.append(
                make_runner_record(
                    deps,
                    principal,
                    AuditOperation.ALLOWLIST_CHANGE,
                    None,
                    before={"entries": before},
                    after={"entries": after},
                    reason=why,
                )
            )
            return AllowlistView({str(k): v for k, v in allowlist.entries.items()})

        return run_in_runner_uow(deps, operate)
