"""受付の判定と待機列への追加(SubmitJob と RetryJob が共有する)。

判定の順序(contracts/application-api.md「共通の約束」): ランナーの判定(FR-002)→ 基準のジョブ(FR-004a)
→ 重複(FR-006)。定義の検証と権限の判定は呼び出し側が先に行う。
"""

from __future__ import annotations

from typing import Any

from job_core.job.domain.definition import JobDefinition, Submitter
from job_core.job.domain.errors import AnchorNotQueued, DuplicateQueuedJob, NoEligibleRunner
from job_core.job.domain.job import Job
from job_core.job.domain.values import Placement
from job_core.shared.ids import JobId

from ..ports import CoreDependencies, UnitOfWork


def admit(
    uow: UnitOfWork,
    deps: CoreDependencies,
    *,
    definition: JobDefinition,
    submitter: Submitter,
    placement: Placement | None,
    retry_of: JobId | None,
) -> tuple[Job, int]:
    """受付の判定を行い、新しいジョブを待機列に並べる。(ジョブ, 位置) を返す。"""
    if not deps.eligibility.any_registered_runner_may_satisfy(definition.requirement):
        raise NoEligibleRunner()
    queue = uow.queue.get()
    if placement is not None and placement.anchor not in queue:
        # 末尾への追加に切り替えず、ジョブ自体を受け付けない(spec Edge Cases)
        raise AnchorNotQueued(placement.anchor)
    key = definition.duplicate_key()
    if key is not None:
        existing = uow.jobs.find_queued_by_duplicate_key(key)
        if existing is not None:
            raise DuplicateQueuedJob(existing.job_id)
    job = Job.submit(
        job_id=JobId(deps.ids.new_id()),
        definition=definition,
        submitter=submitter,
        at=deps.clock.now(),
        retry_of=retry_of,
    )
    uow.jobs.add(job)
    position = queue.append(job.job_id) if placement is None else queue.insert(job.job_id, placement)
    uow.queue.save(queue)
    return job, position


def placement_fields(placement: Placement | None) -> dict[str, Any]:
    """監査記録に残す、位置の指定の項目。"""
    if placement is None:
        return {}
    return {"anchor": placement.anchor, "side": placement.side.value}
