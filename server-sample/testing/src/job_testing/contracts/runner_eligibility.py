"""RunnerEligibility の契約テスト(contracts/ports.md「RunnerEligibility」)。

使い方: 継承したクラスで `eligibility_env` フィクスチャを定義する。値は EligibilityEnv で、
- eligibility: 検査対象の実装
- register(runner_id, capabilities): ランナーを登録する
- unregister(runner_id): 登録を解除する
- requirement_for(capabilities): その能力の組で満たせる要件を作る
002 の実装も同じテストを通す。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from job_core.job.application.ports import RunnerEligibility
from job_core.job.domain.values import RunnerRequirement
from job_core.shared.ids import RunnerId


@dataclass
class EligibilityEnv:
    eligibility: RunnerEligibility
    register: Callable[[str, Mapping[str, object]], None]
    unregister: Callable[[str], None]
    requirement_for: Callable[[Mapping[str, object]], RunnerRequirement]


class RunnerEligibilityContract:
    def test_no_registered_runner_means_no_eligibility(self, eligibility_env: EligibilityEnv) -> None:
        requirement = eligibility_env.requirement_for({"os": "x"})
        assert not eligibility_env.eligibility.any_registered_runner_may_satisfy(requirement)

    def test_registered_runner_satisfies_matching_requirement(self, eligibility_env: EligibilityEnv) -> None:
        eligibility_env.register("r1", {"os": "x", "arch": "y"})
        requirement = eligibility_env.requirement_for({"os": "x"})
        assert eligibility_env.eligibility.any_registered_runner_may_satisfy(requirement)
        assert eligibility_env.eligibility.runner_satisfies(RunnerId("r1"), requirement)

    def test_unmatched_requirement(self, eligibility_env: EligibilityEnv) -> None:
        eligibility_env.register("r1", {"os": "x"})
        requirement = eligibility_env.requirement_for({"os": "z"})
        assert not eligibility_env.eligibility.any_registered_runner_may_satisfy(requirement)
        assert not eligibility_env.eligibility.runner_satisfies(RunnerId("r1"), requirement)

    def test_unknown_or_unregistered_runner(self, eligibility_env: EligibilityEnv) -> None:
        requirement = eligibility_env.requirement_for({"os": "x"})
        assert not eligibility_env.eligibility.runner_satisfies(RunnerId("nobody"), requirement)
        eligibility_env.register("r1", {"os": "x"})
        eligibility_env.unregister("r1")
        assert not eligibility_env.eligibility.any_registered_runner_may_satisfy(requirement)
        assert not eligibility_env.eligibility.runner_satisfies(RunnerId("r1"), requirement)

    def test_queries_have_no_side_effects(self, eligibility_env: EligibilityEnv) -> None:
        eligibility_env.register("r1", {"os": "x"})
        requirement = eligibility_env.requirement_for({"os": "x"})
        results = [
            (
                eligibility_env.eligibility.any_registered_runner_may_satisfy(requirement),
                eligibility_env.eligibility.runner_satisfies(RunnerId("r1"), requirement),
            )
            for _ in range(3)
        ]
        assert results == [(True, True)] * 3
