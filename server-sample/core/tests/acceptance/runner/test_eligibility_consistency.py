"""判定と割り当ての一致(spec SC-001、FR-009。research.md R16)。

ランダムな能力と要件で、「要件を満たしうるか」(any_registered_runner_may_satisfy)が真 ⇔
online にしたそのランナーの RequestJob が割り当てる、が成り立つ(食い違い 0 件)。
文法に合わない要件は、判定がエラーになり、割り当ては行われない(割り当てなし)。
"""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from job_core.job.domain.values import RunnerRequirement
from job_core.runner.application import InvalidRequirement, NotAssignedKind

from .conftest import make_env

single_values = st.sampled_from(["a", "b", "1", "1.5", "2", "10", "1.2.3", "1.10", "abc", "-3"])
set_values = st.frozensets(st.sampled_from(["x", "y", "z"]), max_size=3).map(sorted)

capabilities = st.fixed_dictionaries(
    {},
    optional={"k1": single_values, "k2": single_values, "set1": set_values},
)

ops_single = ["eq", "num_gt", "num_ge", "num_lt", "num_le", "ver_gt", "ver_ge", "ver_lt", "ver_le"]


@st.composite
def conditions(draw: st.DrawFn) -> dict[str, Any]:
    key = draw(st.sampled_from(["k1", "k2", "set1", "missing"]))
    kind = draw(st.sampled_from(["single", "in", "contains", "bad"]))
    if kind == "single":
        op = draw(st.sampled_from(ops_single))
        value = draw(single_values) if op in ("eq",) else draw(st.sampled_from(["1", "1.5", "2", "1.2", "10", "abc"]))
        return {"key": key, "op": op, "value": value}
    if kind == "in":
        return {"key": key, "op": "in", "values": draw(st.lists(single_values, min_size=1, max_size=3))}
    if kind == "contains":
        members = draw(st.lists(st.sampled_from(["x", "y", "z"]), min_size=1, max_size=3))
        return {"key": key, "op": "contains", "values": members}
    bad_op = draw(st.sampled_from(["regex", "num_gt", "ver_ge"]))
    return {"key": key, "op": bad_op, "value": draw(st.sampled_from(["abc", "1.x", ""]))}


requirements = st.lists(conditions(), max_size=3).map(lambda items: {"all": items})


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(capabilities, requirements)
def test_eligibility_and_assignment_never_disagree(caps: dict[str, Any], req: dict[str, Any]) -> None:
    env = make_env()
    handle = env.runner("r-a", caps)
    job_id = env.enqueue_raw(req)
    service = env.core.runner_eligibility
    parsed_ok = True
    try:
        eligible = service.any_registered_runner_may_satisfy(RunnerRequirement.of(req))
        per_runner = service.runner_satisfies(handle.runner_id, RunnerRequirement.of(req))  # type: ignore[arg-type]
    except InvalidRequirement:
        parsed_ok = False
        eligible = per_runner = False

    result = env.request(handle)
    assigned = result.assignment is not None

    assert eligible == per_runner
    assert assigned == eligible, f"判定={eligible} 割り当て={assigned} 能力={caps} 要件={req}"
    if assigned:
        assert result.assignment is not None and result.assignment.job_id == job_id
    else:
        assert result.not_assigned_reason is not None
        assert result.not_assigned_reason.kind is NotAssignedKind.NO_MATCHING_JOB
        assert env.queue_ids() == [job_id]
    assert parsed_ok or not assigned
