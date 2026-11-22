"""JobRepository.search の契約テスト(003 contracts/ports.md「JobRepository.search」)。

使い方は persistence.py と同じ(`new_uow` フィクスチャを定義する)。永続化は空の状態から始めること。
core-persistence(実アダプタ)も同じクラスを継承して実行する。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.job.application.ports import JobSearchCriteria
from job_core.job.domain.errors import ValidationFailed
from job_core.job.domain.states import JobState
from job_core.shared.ids import JobId, SubjectId

from ._builders import T0, finish, make_job
from .persistence import NewUow


def seed(new_uow: NewUow) -> None:
    """alice の j1(待機中)、j2(成功)、bob の j3(待機中)、j4(取り消し)。提出は 1 分おき。"""
    with new_uow() as uow:
        uow.jobs.add(make_job("j1", at=T0, owner="alice"))
        uow.jobs.add(
            finish(
                make_job("j2", at=T0 + timedelta(minutes=1), owner="alice"), JobState.SUCCEEDED, T0 + timedelta(hours=1)
            )
        )
        uow.jobs.add(make_job("j3", at=T0 + timedelta(minutes=2), owner="bob"))
        uow.jobs.add(
            finish(
                make_job("j4", at=T0 + timedelta(minutes=3), owner="bob"), JobState.CANCELLED, T0 + timedelta(hours=1)
            )
        )
        uow.commit()


def ids(new_uow: NewUow, criteria: JobSearchCriteria | None = None, limit: int = 100) -> list[str]:
    with new_uow() as uow:
        return [str(j.job_id) for j in uow.jobs.search(criteria or JobSearchCriteria(), None, limit).items]


class JobSearchContract:
    def test_default_order_is_newest_first(self, new_uow: NewUow) -> None:
        seed(new_uow)
        assert ids(new_uow) == ["j4", "j3", "j2", "j1"]

    def test_each_filter(self, new_uow: NewUow) -> None:
        seed(new_uow)
        assert ids(new_uow, JobSearchCriteria(states=frozenset({JobState.QUEUED}))) == ["j3", "j1"]
        assert ids(new_uow, JobSearchCriteria(states=frozenset({JobState.SUCCEEDED, JobState.CANCELLED}))) == [
            "j4",
            "j2",
        ]
        assert ids(new_uow, JobSearchCriteria(owner=SubjectId("alice"))) == ["j2", "j1"]
        assert ids(new_uow, JobSearchCriteria(submitted_from=T0 + timedelta(minutes=2))) == ["j4", "j3"]
        assert ids(new_uow, JobSearchCriteria(submitted_to=T0 + timedelta(minutes=2))) == ["j2", "j1"]

    def test_time_range_is_inclusive_from_and_exclusive_to(self, new_uow: NewUow) -> None:
        seed(new_uow)
        window = JobSearchCriteria(submitted_from=T0 + timedelta(minutes=1), submitted_to=T0 + timedelta(minutes=3))
        assert ids(new_uow, window) == ["j3", "j2"]

    def test_filters_combine_with_and(self, new_uow: NewUow) -> None:
        seed(new_uow)
        criteria = JobSearchCriteria(states=frozenset({JobState.QUEUED}), owner=SubjectId("bob"))
        assert ids(new_uow, criteria) == ["j3"]
        assert ids(new_uow, JobSearchCriteria(states=frozenset({JobState.RUNNING}))) == []

    def test_same_submission_time_is_ordered_by_job_id_descending(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            for name in ("a", "c", "b"):
                uow.jobs.add(make_job(f"same-{name}", at=T0))
            uow.commit()
        assert ids(new_uow) == ["same-c", "same-b", "same-a"]

    def test_paging_has_no_overlap_or_gap_even_with_changes_between_pages(self, new_uow: NewUow) -> None:
        with new_uow() as uow:
            for i in range(7):
                uow.jobs.add(make_job(f"p{i}", at=T0 + timedelta(minutes=i), owner="alice"))
            uow.commit()
        with new_uow() as uow:
            first = uow.jobs.search(JobSearchCriteria(), None, 3)
            assert [str(j.job_id) for j in first.items] == ["p6", "p5", "p4"] and first.next_cursor
        # 頁の間で、状態の変化・削除・新しい提出が起きる
        with new_uow() as uow:
            job = uow.jobs.get(JobId("p2"))
            assert job is not None
            finish(job, JobState.SUCCEEDED, T0 + timedelta(hours=2))
            uow.jobs.save(job)
            uow.jobs.add(make_job("new", at=T0 + timedelta(hours=3), owner="alice"))
            uow.commit()
        with new_uow() as uow:
            second = uow.jobs.search(JobSearchCriteria(), first.next_cursor, 3)
            assert [str(j.job_id) for j in second.items] == ["p3", "p2", "p1"]
            third = uow.jobs.search(JobSearchCriteria(), second.next_cursor, 3)
            assert [str(j.job_id) for j in third.items] == ["p0"] and third.next_cursor is None

    def test_last_page_has_no_cursor_and_exact_fit_does_not_loop(self, new_uow: NewUow) -> None:
        seed(new_uow)
        with new_uow() as uow:
            page = uow.jobs.search(JobSearchCriteria(), None, 4)
            assert len(page.items) == 4 and page.next_cursor is None

    def test_invalid_cursor_is_a_validation_failure(self, new_uow: NewUow) -> None:
        seed(new_uow)
        for bad in ("not-a-cursor", "", "e30=", "%%%"):
            with new_uow() as uow, pytest.raises(ValidationFailed) as info:
                uow.jobs.search(JobSearchCriteria(), bad, 10)
            assert info.value.field == "cursor"
