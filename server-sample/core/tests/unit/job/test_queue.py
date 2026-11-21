"""待機列(data-model.md §3 の操作と拒否の条件、不変条件)。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from job_core.job.domain.errors import AnchorNotQueued, SelfAnchor, TargetNotQueued
from job_core.job.domain.queue import Queue
from job_core.job.domain.values import Placement, PlacementSide
from job_core.shared.ids import JobId


def queue_of(*ids: str) -> Queue:
    return Queue(entries=[JobId(i) for i in ids])


def test_append_returns_position_at_tail() -> None:
    queue = queue_of("a", "b")
    assert queue.append(JobId("c")) == 3
    assert queue.entries == ["a", "b", "c"]


def test_append_duplicate_is_rejected() -> None:
    with pytest.raises(ValueError):
        queue_of("a").append(JobId("a"))


def test_constructor_rejects_duplicates() -> None:
    with pytest.raises(ValueError):
        queue_of("a", "a")


@pytest.mark.parametrize(
    ("placement", "expected", "position"),
    [
        (Placement.before("a"), ["x", "a", "b", "c"], 1),
        (Placement.after("a"), ["a", "x", "b", "c"], 2),
        (Placement.before("c"), ["a", "b", "x", "c"], 3),
        (Placement.after("c"), ["a", "b", "c", "x"], 4),
    ],
)
def test_insert(placement: Placement, expected: list[str], position: int) -> None:
    queue = queue_of("a", "b", "c")
    assert queue.insert(JobId("x"), placement) == position
    assert queue.entries == expected


def test_insert_with_missing_anchor_is_rejected_without_change() -> None:
    queue = queue_of("a")
    with pytest.raises(AnchorNotQueued):
        queue.insert(JobId("x"), Placement.before("zzz"))
    assert queue.entries == ["a"]


def test_insert_into_empty_queue_is_rejected() -> None:
    with pytest.raises(AnchorNotQueued):
        Queue().insert(JobId("x"), Placement.before("a"))


@pytest.mark.parametrize(
    ("job", "placement", "expected", "positions"),
    [
        ("c", Placement.before("a"), ["c", "a", "b"], (3, 1)),
        ("a", Placement.after("b"), ["b", "a", "c"], (1, 2)),
        ("a", Placement.after("c"), ["b", "c", "a"], (1, 3)),
        ("c", Placement.after("a"), ["a", "c", "b"], (3, 2)),
    ],
)
def test_move(job: str, placement: Placement, expected: list[str], positions: tuple[int, int]) -> None:
    queue = queue_of("a", "b", "c")
    assert queue.move(JobId(job), placement) == positions
    assert queue.entries == expected


def test_move_that_does_not_change_position_succeeds() -> None:
    queue = queue_of("a", "b", "c")
    assert queue.move(JobId("a"), Placement.before("b")) == (1, 1)
    assert queue.entries == ["a", "b", "c"]


def test_move_rejections() -> None:
    queue = queue_of("a", "b")
    with pytest.raises(SelfAnchor):
        queue.move(JobId("a"), Placement.before("a"))
    with pytest.raises(TargetNotQueued):
        queue.move(JobId("zzz"), Placement.before("a"))
    with pytest.raises(AnchorNotQueued):
        queue.move(JobId("a"), Placement.before("zzz"))
    assert queue.entries == ["a", "b"]


def test_remove_closes_gap() -> None:
    queue = queue_of("a", "b", "c")
    assert queue.remove(JobId("a")) == 1
    assert queue.entries == ["b", "c"]
    assert queue.position_of(JobId("b")) == 1
    with pytest.raises(TargetNotQueued):
        queue.remove(JobId("a"))


def test_first_matching() -> None:
    queue = queue_of("a", "b", "c")
    assert queue.first_matching(lambda j: j in {"b", "c"}) == "b"
    assert queue.first_matching(lambda j: False) is None


# ------------------------------------------------------------ 不変条件(property-based)

operations = st.lists(
    st.tuples(
        st.sampled_from(["append", "insert", "move", "remove"]),
        st.integers(min_value=0, max_value=30),
        st.integers(min_value=0, max_value=30),
        st.sampled_from([PlacementSide.BEFORE, PlacementSide.AFTER]),
    ),
    max_size=60,
)


@settings(max_examples=200, deadline=None)
@given(operations)
def test_invariants_hold_for_any_sequence(ops: list[tuple[str, int, int, PlacementSide]]) -> None:
    queue = Queue()
    for name, a, b, side in ops:
        target, anchor = JobId(f"j{a}"), JobId(f"j{b}")
        before = list(queue.entries)
        try:
            if name == "append":
                queue.append(target)
            elif name == "insert":
                queue.insert(target, Placement(anchor, side))
            elif name == "move":
                queue.move(target, Placement(anchor, side))
            else:
                queue.remove(target)
        except (ValueError, AnchorNotQueued, TargetNotQueued, SelfAnchor):
            assert queue.entries == before  # 拒否された操作は何も変えない
            continue
        # 重複なし
        assert len(set(queue.entries)) == len(queue.entries)
        # 対象以外の相対的な順序は変わらない
        others_before = [j for j in before if j != target]
        others_after = [j for j in queue.entries if j != target]
        assert others_before == others_after
        # 位置の一貫性
        for index, job_id in enumerate(queue.entries, start=1):
            assert queue.position_of(job_id) == index
        # 移動・追加では、指定した位置に入る
        if name in ("insert", "move"):
            pos_target = queue.entries.index(target)
            pos_anchor = queue.entries.index(anchor)
            assert pos_target == (pos_anchor - 1 if side is PlacementSide.BEFORE else pos_anchor + 1)
