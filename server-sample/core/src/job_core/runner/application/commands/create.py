"""CreateRunner — ランナーの作成(US1、FR-001、FR-022。contracts/application-api.md「CreateRunner」)。"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.runner.domain.errors import DuplicateRunnerName
from job_core.runner.domain.runner import Runner
from job_core.runner.domain.token import IssuedToken, RunnerToken, hash_token
from job_core.runner.domain.values import RunnerName
from job_core.shared.ids import RunnerId

from ..audit import audited, make_runner_record
from ..authorization import authorize_manage
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import CreatedRunner
from ..uow_support import run_in_runner_uow


class CreateRunner:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, name: str) -> CreatedRunner:
        deps = self._deps
        audited(
            deps,
            principal,
            AuditOperation.RUNNER_CREATE,
            None,
            lambda: authorize_manage(principal),
            attempted={"name": name if isinstance(name, str) else None},
        )
        runner_name = RunnerName(name)

        def operate(uow: RunnerUnitOfWork) -> CreatedRunner:
            now = deps.clock.now()
            runner = Runner.create(RunnerId(deps.ids.new_id()), runner_name, now)
            if any(existing.name == runner_name for existing in uow.runners.list_active()):
                raise DuplicateRunnerName(runner_name.value)
            uow.runners.add(runner)
            value = deps.secrets.new_token()
            token = RunnerToken.issue(
                token_id=deps.ids.new_id(), runner_id=runner.runner_id, token_hash=hash_token(value), at=now
            )
            uow.tokens.add(token)
            uow.audit.append(
                make_runner_record(
                    deps, principal, AuditOperation.RUNNER_CREATE, runner.runner_id, after={"name": runner_name.value}
                )
            )
            uow.audit.append(
                make_runner_record(
                    deps, principal, AuditOperation.TOKEN_ISSUE, runner.runner_id, after={"token_id": token.token_id}
                )
            )
            return CreatedRunner(runner.runner_id, IssuedToken(token.token_id, value))

        return run_in_runner_uow(deps, operate)
