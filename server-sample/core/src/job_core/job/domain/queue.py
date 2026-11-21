"""Queue 集約(data-model.md §3。Queue.queue_id、Queue.entries、Queue.version)。

待機中のジョブの明示的な並び。移動・追加・取り出しで、対象以外の相対的な順序は変わらない(FR-011)。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from job_core.shared.ids import JobId

from .errors import AnchorNotQueued, SelfAnchor, TargetNotQueued
from .values import Placement, PlacementSide

DEFAULT_QUEUE_ID = "default"


@dataclass(eq=False)
class Queue:
    queue_id: str = DEFAULT_QUEUE_ID
    entries: list[JobId] = field(default_factory=list)
    version: int = 0

    def __post_init__(self) -> None:
        if len(set(self.entries)) != len(self.entries):
            raise ValueError("Queue.entries に同じジョブが 2 度現れてはならない")

    def __contains__(self, job_id: object) -> bool:
        return job_id in self.entries

    def __len__(self) -> int:
        return len(self.entries)

    def position_of(self, job_id: JobId) -> int | None:
        """1 始まりの位置。待機列になければ None。"""
        try:
            return self.entries.index(job_id) + 1
        except ValueError:
            return None

    def append(self, job_id: JobId) -> int:
        """末尾に追加し、位置を返す(FR-004)。"""
        self._require_absent(job_id)
        self.entries.append(job_id)
        return len(self.entries)

    def insert(self, job_id: JobId, placement: Placement) -> int:
        """基準のジョブの直前/直後に追加し、位置を返す(FR-004a)。基準がなければ末尾に切り替えず拒否する。"""
        self._require_absent(job_id)
        index = self._index_of_anchor(placement.anchor)
        if placement.side is PlacementSide.AFTER:
            index += 1
        self.entries.insert(index, job_id)
        return index + 1

    def move(self, job_id: JobId, placement: Placement) -> tuple[int, int]:
        """対象を基準のジョブの直前/直後へ移し、(移動前の位置, 移動後の位置) を返す(FR-011、FR-012)。"""
        if job_id == placement.anchor:
            raise SelfAnchor()
        if job_id not in self.entries:
            raise TargetNotQueued(job_id)
        self._index_of_anchor(placement.anchor)
        before = self.entries.index(job_id) + 1
        self.entries.remove(job_id)
        index = self.entries.index(placement.anchor)
        if placement.side is PlacementSide.AFTER:
            index += 1
        self.entries.insert(index, job_id)
        return before, index + 1

    def remove(self, job_id: JobId) -> int:
        """取り出し(割り当て・取り消し)。取り出した位置を返す。"""
        if job_id not in self.entries:
            raise TargetNotQueued(job_id)
        position = self.entries.index(job_id) + 1
        self.entries.remove(job_id)
        return position

    def first_matching(self, predicate: Callable[[JobId], bool]) -> JobId | None:
        """先頭から走査して、最初に条件を満たすジョブ(FR-009)。"""
        for job_id in self.entries:
            if predicate(job_id):
                return job_id
        return None

    def _require_absent(self, job_id: JobId) -> None:
        if job_id in self.entries:
            raise ValueError(f"ジョブ {job_id} は既に待機列にある")

    def _index_of_anchor(self, anchor: JobId) -> int:
        try:
            return self.entries.index(anchor)
        except ValueError:
            raise AnchorNotQueued(anchor) from None
