"""AppendLog — ランナーからのログのチャンクの追加(004 contracts/runner-protocol.md §3.1)。

割り当て先のランナー(JOB_EXECUTE)だけが、実行中のジョブに追加できる。(job_id, seq) の冪等。
総量の上限を超える追加は LogQuotaExceeded。成功の追加は監査に残さない(量が多いため)。
権限による拒否・割り当て先の不一致は監査に DENIED を残す。
"""

from __future__ import annotations

from job_core.access.principal import Principal
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import JobNotFound, RunnerMismatch, TargetNotRunning, ValidationFailed
from job_core.job.domain.output import JobLogChunk, LogStream
from job_core.job.domain.states import JobState
from job_core.shared.ids import JobId, RunnerId

from ..audit_support import audited_denials
from ..authorization import authorize_execute
from ..ports import AppendResult, CoreDependencies


class AppendLog:
    def __init__(self, deps: CoreDependencies) -> None:
        self._deps = deps

    def __call__(
        self,
        principal: Principal,
        *,
        runner_id: str,
        job_id: str,
        seq: int,
        stream: LogStream | str,
        text: str,
    ) -> AppendResult:
        deps = self._deps
        outputs = deps.outputs
        if outputs is None:
            raise ValidationFailed("outputs", "ログの保存先が構成されていない")
        try:
            log_stream = LogStream(stream)
        except ValueError as exc:
            raise ValidationFailed("stream", "stdout または stderr でなければならない") from exc
        chunk = JobLogChunk(seq=seq, stream=log_stream, text=text)
        runner = RunnerId(runner_id)
        target = JobId(job_id)

        def operate() -> AppendResult:
            authorize_execute(principal)
            with deps.uow_factory() as uow:
                job = uow.jobs.get(target)
            if job is None:
                raise JobNotFound(target)
            if job.state is not JobState.RUNNING:
                raise TargetNotRunning(target, job.state.value)
            if job.assigned_runner_id != runner:
                raise RunnerMismatch(target)
            return outputs.append(target, chunk, deps.clock.now(), deps.log_quota_chars)

        return audited_denials(
            deps,
            principal,
            AuditOperation.RUNNER_JOB_REPORT,
            target,
            operate,
            attempted={"runner_id": runner, "log_seq": seq},
        )
