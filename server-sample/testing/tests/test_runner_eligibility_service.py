"""001 の RunnerEligibilityContract を、002 の RunnerEligibilityService で実行する(contracts/ports.md)。

requirement_for は {"all": [{"key", "op": "eq", "value"}...]} を作る。能力のキーは、許可リストに載せて登録する。
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from job_core.access.principal import Principal
from job_core.job.domain.values import RunnerRequirement
from job_testing.contracts.runner_eligibility import EligibilityEnv, RunnerEligibilityContract
from job_testing.core_fakes import build_core

ADMIN = Principal.of("admin", {"runner.manage", "job.general"})


@pytest.fixture
def eligibility_env() -> EligibilityEnv:
    core = build_core(use_runner_management=True)
    core.replace_allowlist(ADMIN, entries={"os": "single", "arch": "single"})
    ids: dict[str, str] = {}

    def register(runner_id: str, capabilities: Mapping[str, object]) -> None:
        created = core.create_runner(ADMIN, name=runner_id)
        ids[runner_id] = created.runner_id
        principal = core.authenticate_runner(created.token.value)
        core.register_runner(principal, runner_id=created.runner_id, capabilities=dict(capabilities))

    def unregister(runner_id: str) -> None:
        core.delete_runner(ADMIN, runner_id=ids[runner_id])

    class Adapter:
        """契約テストの runner_id(名前)を、002 の識別子に読み替える。"""

        def any_registered_runner_may_satisfy(self, requirement: RunnerRequirement) -> bool:
            return core.runner_eligibility.any_registered_runner_may_satisfy(requirement)

        def runner_satisfies(self, runner_id: str, requirement: RunnerRequirement) -> bool:
            actual = ids.get(runner_id, runner_id)
            return core.runner_eligibility.runner_satisfies(actual, requirement)  # type: ignore[arg-type]

    def requirement_for(capabilities: Mapping[str, object]) -> RunnerRequirement:
        return RunnerRequirement.of(
            {"all": [{"key": key, "op": "eq", "value": value} for key, value in capabilities.items()]}
        )

    return EligibilityEnv(
        eligibility=Adapter(),  # type: ignore[arg-type]
        register=register,
        unregister=unregister,
        requirement_for=requirement_for,
    )


class TestRunnerEligibilityService(RunnerEligibilityContract):
    pass
