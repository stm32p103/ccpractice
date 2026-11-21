"""ReissueToken / RevokeToken — ランナーのトークンの再発行と失効(US7、FR-022、FR-023。research.md R9)。

再発行は、旧トークンの失効と新トークンの発行を同じ UoW で行う(有効なトークンは高々 1 つ。不変条件 3)。
トークンの値は ReissueToken の戻り値にだけ現れる。監査には token_id だけを残す。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.values import Reason
from job_core.runner.domain.token import IssuedToken, RunnerToken, hash_token
from job_core.shared.ids import RunnerId

from ..audit import audited, make_runner_record
from ..authorization import authorize_manage
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..uow_support import run_in_runner_uow
from ._common import load_runner


class ReissueToken:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, reason: str | None = None) -> IssuedToken:
        deps = self._deps
        target = RunnerId(runner_id)
        audited(deps, principal, AuditOperation.TOKEN_ISSUE, target, lambda: authorize_manage(principal))
        why = Reason(reason).value if reason is not None else None

        def operate(uow: RunnerUnitOfWork) -> IssuedToken:
            load_runner(uow, runner_id)
            now = deps.clock.now()
            old = uow.tokens.find_valid_by_runner(target)
            if old is not None:
                old.revoke(now)
                uow.tokens.save(old)
                uow.audit.append(
                    make_runner_record(
                        deps,
                        principal,
                        AuditOperation.TOKEN_REVOKE,
                        target,
                        before={"token_id": old.token_id},
                        reason=why,
                    )
                )
            value = deps.secrets.new_token()
            new = RunnerToken.issue(token_id=deps.ids.new_id(), runner_id=target, token_hash=hash_token(value), at=now)
            uow.tokens.add(new)
            uow.audit.append(
                make_runner_record(
                    deps,
                    principal,
                    AuditOperation.TOKEN_ISSUE,
                    target,
                    before={"token_id": old.token_id if old else None},
                    after={"token_id": new.token_id},
                    reason=why,
                )
            )
            return IssuedToken(new.token_id, value)

        return run_in_runner_uow(deps, operate)


class RevokeToken:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str, reason: str | None = None) -> None:
        deps = self._deps
        target = RunnerId(runner_id)
        audited(deps, principal, AuditOperation.TOKEN_REVOKE, target, lambda: authorize_manage(principal))
        why = Reason(reason).value if reason is not None else None

        def operate(uow: RunnerUnitOfWork) -> None:
            load_runner(uow, runner_id)
            token = uow.tokens.find_valid_by_runner(target)
            if token is None:
                return  # 有効なトークンがなければ、変化なしで成功する
            token.revoke(deps.clock.now())
            uow.tokens.save(token)
            uow.audit.append(
                make_runner_record(
                    deps,
                    principal,
                    AuditOperation.TOKEN_REVOKE,
                    target,
                    before={"token_id": token.token_id},
                    reason=why,
                )
            )

        run_in_runner_uow(deps, operate)
