"""US2: 要件を満たしうるランナーがいるかを判定する(spec US2-1〜US2-6、FR-007〜FR-009)。"""

from __future__ import annotations

import pytest

from job_core.job.application import NoEligibleRunner
from job_core.job.domain.errors import ValidationFailed
from job_core.job.domain.values import RunnerRequirement
from job_core.runner.application import InvalidRequirement
from job_core.shared.ids import RunnerId

from .conftest import RunnerEnv, contains, eq, requirement


def may_satisfy(env: RunnerEnv, req: dict[str, object]) -> bool:
    return env.core.runner_eligibility.any_registered_runner_may_satisfy(RunnerRequirement.of(req))


def test_us2_1_offline_runner_with_matching_capabilities_may_satisfy(env: RunnerEnv) -> None:
    env.runner("r-a", {"k1": "a"})
    env.advance(300)  # offline
    assert may_satisfy(env, requirement(eq("k1", "a")))
    assert env.submit(requirement(eq("k1", "a"))).job_id  # 提出も受け付けられる


def test_us2_2_no_runner_satisfies(env: RunnerEnv) -> None:
    env.runner("r-a", {"k1": "a"})
    assert not may_satisfy(env, requirement(eq("k1", "b")))
    with pytest.raises(NoEligibleRunner):
        env.submit(requirement(eq("k1", "b")))
    assert env.queue_ids() == []


def test_us2_3_deleted_sole_runner_no_longer_satisfies(env: RunnerEnv) -> None:
    handle = env.runner("r-a", {"k1": "a"})
    assert may_satisfy(env, requirement(eq("k1", "a")))
    env.core.delete_runner(env.admin, runner_id=handle.runner_id)
    assert not may_satisfy(env, requirement(eq("k1", "a")))
    with pytest.raises(NoEligibleRunner):
        env.submit(requirement(eq("k1", "a")))


def test_us2_4_never_registered_runner_satisfies_only_empty_requirement(env: RunnerEnv) -> None:
    env.runner("r-a", register=False)
    assert not may_satisfy(env, requirement(eq("k1", "a")))
    assert may_satisfy(env, requirement())  # 空の要件は、登録済みでないランナーでも満たす
    assert may_satisfy(env, requirement()) is True


def test_no_runner_at_all_means_not_satisfiable_even_for_empty_requirement(env: RunnerEnv) -> None:
    assert not may_satisfy(env, requirement())
    with pytest.raises(NoEligibleRunner):
        env.submit(requirement())


@pytest.mark.parametrize(
    "bad",
    [
        {"all": [{"key": "k1", "op": "regex", "value": "a"}]},  # 未知の比較の種類
        {"all": [{"key": "k1", "op": "num_gt", "value": "abc"}]},  # 数値でない値への数値の比較
        {"all": [{"key": "k1", "op": "ver_ge", "value": "1.x"}]},
        {"all": [{"key": "k1", "op": "contains", "values": "a"}]},
        {"k1": "a"},  # 001 の Fake 用の形は 002 では文法のエラー
        {"all": [{"key": "K1", "op": "eq", "value": "a"}]},
    ],
)
def test_us2_5_invalid_requirement_is_an_error_not_a_yes(env: RunnerEnv, bad: dict[str, object]) -> None:
    env.runner("r-a", {"k1": "a"})
    with pytest.raises(InvalidRequirement):
        may_satisfy(env, bad)
    with pytest.raises(ValidationFailed) as err:
        env.submit(bad)
    assert err.value.field == "requirement"
    assert env.queue_ids() == []


def test_invalid_requirement_is_an_error_even_without_runners(env: RunnerEnv) -> None:
    with pytest.raises(ValidationFailed):
        env.submit({"all": [{"key": "k1", "op": "regex", "value": "a"}]})


def test_us2_6_set_capability_with_contains(env: RunnerEnv) -> None:
    env.runner("r-a", {"set1": ["x", "y"]})
    assert may_satisfy(env, requirement(contains("set1", "y")))
    assert may_satisfy(env, requirement(contains("set1", "x", "y")))
    assert not may_satisfy(env, requirement(contains("set1", "z")))


def test_state_and_busy_are_not_considered(env: RunnerEnv) -> None:
    maintenance = env.runner("r-m", {"k1": "m"})
    faulty = env.runner("r-f", {"k1": "f"})
    env.core.set_maintenance(env.admin, runner_id=maintenance.runner_id)
    env.core.report_fault(faulty.principal, runner_id=faulty.runner_id, description="e1")
    assert may_satisfy(env, requirement(eq("k1", "m")))
    assert may_satisfy(env, requirement(eq("k1", "f")))


def test_runner_satisfies_unknown_or_deleted_is_false(env: RunnerEnv) -> None:
    handle = env.runner("r-a", {"k1": "a"})
    req = RunnerRequirement.of(requirement(eq("k1", "a")))
    service = env.core.runner_eligibility
    assert service.runner_satisfies(RunnerId(handle.runner_id), req)
    assert not service.runner_satisfies(RunnerId("nobody"), req)
    env.core.delete_runner(env.admin, runner_id=handle.runner_id)
    assert not service.runner_satisfies(RunnerId(handle.runner_id), req)
