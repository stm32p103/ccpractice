"""RunnerEligibilityService — 001 の RunnerEligibility ポートの実装(contracts/application-api.md「001 への契約」)。

RunnerCatalog と、照合の純粋関数(parse_requirement、satisfies)だけを使う。ランナーの状態(online / offline /
異常 / maintenance)と、空いているかどうかは見ない(FR-008)。割り当て(RequestJob)も同じ関数で照合する(FR-009)。
要件が文法に合わなければ InvalidRequirement を送出する(001 の提出は、これを検証の誤りとして拒否する)。
"""

from __future__ import annotations

from job_core.job.domain.values import RunnerRequirement
from job_core.runner.domain.matching import parse_requirement, satisfies
from job_core.shared.ids import RunnerId

from .ports import RunnerCatalog


class RunnerEligibilityService:
    def __init__(self, catalog: RunnerCatalog) -> None:
        self._catalog = catalog

    def any_registered_runner_may_satisfy(self, requirement: RunnerRequirement) -> bool:
        parsed = parse_requirement(requirement)  # 文法のエラーは、ランナーの有無に関わらず送出する
        return any(satisfies(capabilities, parsed) for _, capabilities in self._catalog.active_capabilities())

    def runner_satisfies(self, runner_id: RunnerId, requirement: RunnerRequirement) -> bool:
        capabilities = self._catalog.capabilities_of(runner_id)
        if capabilities is None:
            return False
        return satisfies(capabilities, parse_requirement(requirement))
