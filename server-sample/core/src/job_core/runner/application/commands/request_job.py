"""RequestJob — 割り当ての要求(US3、FR-013〜FR-015。research.md R4)。

1 回の UoW で、ランナーの状態の確認 → 001 の割り当ての本体(assign_next_in。このランナーの能力での照合)→
リースの作成を確定する。「割り当てなし」は例外ではなく結果として返す(ランナーは定期的に求め直す)。

状態は「この要求を受ける前」の最終応答時刻で判断する(offline のランナーは、先に生存通知で online に戻す)。
要求そのものも、生存の証拠として最終応答時刻を更新する(spec の前提)。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.application.commands.assign import assign_next_in
from job_core.job.application.queries.job_views import definition_view
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.values import RunnerRequirement
from job_core.runner.domain.errors import InvalidRequirement
from job_core.runner.domain.lease import Lease
from job_core.runner.domain.matching import parse_requirement, satisfies
from job_core.runner.domain.runner import RunnerState
from job_core.runner.domain.values import Capabilities
from job_core.shared.ids import JobId, RunnerId

from ..audit import append_connectivity_change, audited
from ..authorization import authorize_request_job, require_self
from ..ports import RunnerDependencies, RunnerUnitOfWork
from ..results import Assignment, JobRequestResult, NotAssignedKind, NotAssignedReason
from ..uow_support import run_in_runner_uow
from ._common import load_runner, settle_lease


def _satisfied_by(capabilities: Capabilities, requirement: RunnerRequirement) -> bool:
    """判定(RunnerEligibilityService)と同じ照合の規則。文法に合わない要件は、満たさない(割り当てない)として扱う。"""
    try:
        return satisfies(capabilities, parse_requirement(requirement))
    except InvalidRequirement:
        return False


class RequestJob:
    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps

    def __call__(self, principal: Principal, *, runner_id: str) -> JobRequestResult:
        deps = self._deps
        target = RunnerId(runner_id)

        def checked() -> JobRequestResult:
            authorize_request_job(principal)
            require_self(principal, target)
            return run_in_runner_uow(deps, operate)

        def not_assigned(reason: NotAssignedReason) -> JobRequestResult:
            return JobRequestResult(None, reason, deps.timing.heartbeat_interval)

        def operate(uow: RunnerUnitOfWork) -> JobRequestResult:
            runner = load_runner(uow, runner_id)
            now = deps.clock.now()
            state = runner.state_at(now, deps.timing)  # 要求を受ける前の状態
            runner.seen(now)
            uow.runners.save(runner)
            append_connectivity_change(deps, uow.audit, principal, runner, now=now)
            if state is not RunnerState.ONLINE:
                return not_assigned(NotAssignedReason(NotAssignedKind.NOT_ONLINE, state=state))
            settle_lease(uow, target)  # 終了したジョブのリースを整理する
            busy = uow.jobs.find_unfinished_by_runner(target)
            if busy is not None:
                return not_assigned(NotAssignedReason(NotAssignedKind.RUNNER_BUSY, job_id=busy.job_id))

            capabilities = runner.capabilities
            lease_id = deps.ids.new_id()
            result = assign_next_in(
                uow,
                deps,
                principal,
                target,
                lambda requirement: _satisfied_by(capabilities, requirement),
                lease_id=lease_id,
            )
            if result.job_id is None:
                return not_assigned(NotAssignedReason(NotAssignedKind.NO_MATCHING_JOB))
            job = uow.jobs.get(JobId(result.job_id))
            if job is None:  # pragma: no cover - 割り当てた直後のジョブが存在しない
                raise RuntimeError(f"割り当てたジョブ {result.job_id} が存在しない")
            lease = Lease.grant(lease_id=lease_id, job_id=job.job_id, runner_id=target, now=now, policy=deps.timing)
            uow.leases.add(lease)
            assignment = Assignment(
                job_id=job.job_id,
                definition=definition_view(job),
                lease_id=lease.lease_id,
                lease_expires_at=lease.expires_at,
            )
            return JobRequestResult(assignment, None, deps.timing.heartbeat_interval)

        return audited(deps, principal, AuditOperation.ASSIGN, target, checked, attempted={"runner_id": target})
