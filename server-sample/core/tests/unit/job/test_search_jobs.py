"""SearchJobs(003 research.md R8)。権限、絞り込み、位置、payload を含まないこと、不正な入力。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.access.permission import Permission as P
from job_core.access.principal import Principal
from job_core.job.domain.errors import PermissionDenied, ValidationFailed
from job_testing.core_fakes import build_core

ALICE = Principal.of("alice", [P.JOB_SUBMIT, P.GENERAL])
VIEWER = Principal.of("viewer", [P.GENERAL])
NOBODY = Principal.of("nobody", [])


def submit_n(core, n: int, principal: Principal = ALICE) -> list[str]:  # type: ignore[no-untyped-def]
    core.runners.register("R1", {"os": "x"})
    ids = []
    for i in range(n):
        result = core.submit(
            principal,
            job_type="t",
            requirement={"os": "x"},
            payload={"secret-payload": i},
            timeout=timedelta(minutes=1),
        )
        ids.append(str(result.job_id))
        core.clock.advance(timedelta(seconds=1))
    return ids


def test_requires_general_permission() -> None:
    core = build_core()
    with pytest.raises(PermissionDenied):
        core.search_jobs(NOBODY)
    assert core.search_jobs(VIEWER).items == ()


def test_returns_newest_first_with_queue_positions_and_no_payload() -> None:
    core = build_core()
    ids = submit_n(core, 3)
    page = core.search_jobs(VIEWER)
    assert [str(i.job_id) for i in page.items] == list(reversed(ids))
    assert [i.position for i in page.items] == [3, 2, 1]
    assert "secret-payload" not in repr(page)


def test_filters_and_paging() -> None:
    core = build_core()
    ids = submit_n(core, 5)
    first = core.search_jobs(VIEWER, limit=2)
    assert len(first.items) == 2 and first.next_cursor
    rest = core.search_jobs(VIEWER, limit=10, cursor=first.next_cursor)
    assert [str(i.job_id) for i in first.items + rest.items] == list(reversed(ids))
    assert core.search_jobs(VIEWER, owner="alice", states=["queued"]).items
    assert core.search_jobs(VIEWER, owner="bob").items == ()
    assert core.search_jobs(VIEWER, states=["succeeded"]).items == ()


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 201}, "limit"),
        ({"cursor": "garbage"}, "cursor"),
        ({"states": ["no-such-state"]}, "states"),
    ],
)
def test_invalid_input_is_a_validation_failure(kwargs: dict[str, object], field: str) -> None:
    core = build_core()
    with pytest.raises(ValidationFailed) as info:
        core.search_jobs(VIEWER, **kwargs)  # type: ignore[arg-type]
    assert info.value.field == field
