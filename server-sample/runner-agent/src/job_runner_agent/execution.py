"""1 件のジョブの実行(data-model.md §1.3。research.md R5〜R14)。

assigned → preparing(許可リスト・作業フォルダ・取得・実行計画の検証)→ running → collecting → reporting → cleaning。
どの経路でも cleaning を通る(作業フォルダの削除、取得資格の破棄、ジャーナルの整理)。
エグゼキュータはプロセスを起動しない(計画を返すだけ)。起動できるのは設定の tool_id だけ。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import NoReturn

from job_runner_protocol.messages import ArtifactReference, Counters, FinishReport
from job_runner_protocol.vocabulary import FailureReason, Outcome, Stream

from .artifacts.collect import ArtifactLimitExceeded, collect, compile_pattern
from .artifacts.port import ArtifactStore, ArtifactStoreError
from .core_client import Assignment, CoreClient, CoreRejected
from .executor import (
    Arg,
    ExecutionContext,
    Executor,
    ExecutorRejected,
    Literal,
    ProcessOutcome,
    Verdict,
    default_verdict,
)
from .guard.allowlist import NotAllowed, RepositoryAllowlist, ToolRegistry
from .guard.environment import EnvRejected, build_environment
from .guard.masking import mask_text
from .guard.workpath import PathRejected, WorkFolder, WorkPath
from .journal import AgentJournal
from .launcher.port import LaunchSpec, ProcessLauncher, RunningProcess
from .logs import LogSender, LogSummary
from .retry import retry_unavailable
from .settings import AgentSettings, ExecutorBinding
from .signals import SignalWatcher
from .source import SourceFetcher, SourceUnavailable

SIGNAL_POLL_SECONDS = 1.0


@dataclass
class AgentContext:
    """実行に使うポートと設定の束。"""

    settings: AgentSettings
    client: CoreClient
    launcher: ProcessLauncher
    executors: Mapping[str, Executor]
    journal: AgentJournal
    secrets: list[str] = field(default_factory=list)
    fetcher: SourceFetcher | None = None
    artifact_store: ArtifactStore | None = None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    clock: Callable[[], float] = time.monotonic


class _Fail(Exception):
    def __init__(self, reason: FailureReason, summary: str | None = None) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.summary = summary


@dataclass
class _Prepared:
    folder: WorkFolder
    context: ExecutionContext
    spec: LaunchSpec
    patterns: list[str]


@dataclass
class _Result:
    kind: str
    """report、stopped、lease_lost、shutdown のいずれか。"""
    report: FinishReport | None = None


class JobRun:
    def __init__(
        self,
        agent: AgentContext,
        assignment: Assignment,
        heartbeat_interval: float,
        stop: asyncio.Event,
    ) -> None:
        self.agent = agent
        self.assignment = assignment
        self.interval = heartbeat_interval
        self.stop = stop
        self.abort = asyncio.Event()
        self.lease_lost = asyncio.Event()
        self.path_rejections = 0
        self.masked_extra = 0
        self.secrets = list(agent.secrets)
        self._folder: WorkFolder | None = None
        self._heartbeat: asyncio.Task[None] | None = None
        self._delivered = False

    # ------------------------------------------------------------------ 公開

    async def run(self) -> None:
        a, journal = self.assignment, self.agent.journal
        journal.write_active(a.job_id, a.lease_id, journal.now_text())
        self._heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            result = await self._execute()
            await self._deliver(result)
        finally:
            if self._heartbeat is not None:
                self._heartbeat.cancel()
                await asyncio.gather(self._heartbeat, return_exceptions=True)
            await self._cleanup()

    # ------------------------------------------------------------------ 生存通知

    async def _heartbeat_loop(self) -> None:
        agent = self.agent
        interval = self.interval
        while True:
            await agent.sleep(interval)
            try:
                result = await agent.client.heartbeat()
            except CoreRejected:
                continue
            except Exception:
                continue
            interval = result.heartbeat_interval_seconds
            if result.lease_expires_at is None:
                self.lease_lost.set()
            if result.abort_requested:
                self.abort.set()

    # ------------------------------------------------------------------ 実行

    def _failed(self, reason: FailureReason, summary: str | None = None, exit_code: int | None = None) -> _Result:
        report = FinishReport(
            Outcome.FAILED,
            summary,
            exit_code,
            reason,
            (),
            Counters(self.path_rejections, self.masked_extra, False),
        )
        return _Result("report", report)

    async def _execute(self) -> _Result:
        agent, a = self.agent, self.assignment
        settings = agent.settings
        if a.source is not None and not RepositoryAllowlist(settings.source.repository_allowlist).is_allowed(a.source):
            agent.journal.audit("repository_rejected", a.job_id)
            return self._failed(FailureReason.REPOSITORY_NOT_ALLOWED)
        binding = settings.executors.get(a.job_type)
        executor = agent.executors.get(a.job_type)
        if binding is None or executor is None:
            return self._failed(FailureReason.UNSUPPORTED_JOB_TYPE)
        try:
            async with asyncio.timeout(settings.timeouts.prepare_timeout_seconds):
                prepared = await self._prepare(binding, executor)
        except TimeoutError:
            return self._failed(FailureReason.PREPARE_TIMEOUT)
        except _Fail as failure:
            return self._failed(failure.reason, failure.summary)
        if self.abort.is_set():
            return _Result("stopped")
        if self.lease_lost.is_set():
            return _Result("lease_lost")
        return await self._run_tool(prepared, executor)

    async def _prepare(self, binding: ExecutorBinding, executor: Executor) -> _Prepared:
        agent, a = self.agent, self.assignment
        settings, journal = agent.settings, agent.journal
        try:
            folder = await asyncio.to_thread(WorkFolder.create, Path(settings.work.root), a.job_id)
        except OSError:
            raise _Fail(FailureReason.ARTIFACT_STORE_FAILED, None) from None  # 作業フォルダを作れない
        self._folder = folder
        source_dir: WorkPath | None = None
        if a.source is not None:
            source_dir = folder.path_of("src")
            await self._fetch_source(source_dir)
        context = ExecutionContext(
            job_id=a.job_id,
            job_type=a.job_type,
            payload=a.payload if isinstance(a.payload, Mapping) else {"value": a.payload},
            timeout=_seconds(a.timeout_seconds),
            work=folder,
            source_dir=source_dir,
            options=binding.options,
        )
        try:
            plan = executor.prepare(context)
        except ExecutorRejected:
            raise _Fail(FailureReason.INPUT_REJECTED) from None
        except PathRejected as rejected:  # エグゼキュータが WorkFolder.resolve() で検査に落ちた
            self._reject_path(rejected)
        except Exception as exc:
            journal.audit("executor_error", a.job_id, kind=type(exc).__name__)
            raise _Fail(FailureReason.EXECUTOR_ERROR) from None
        return self._validate_plan(plan, binding, folder, context)

    def _validate_plan(
        self, plan: object, binding: ExecutorBinding, folder: WorkFolder, context: ExecutionContext
    ) -> _Prepared:
        agent, a = self.agent, self.assignment
        settings, journal = agent.settings, agent.journal
        try:
            tool = ToolRegistry(settings.tools).resolve(plan.tool_id, binding.tool_ids)  # type: ignore[attr-defined]
        except NotAllowed:
            journal.audit("tool_not_registered", a.job_id)
            raise _Fail(FailureReason.INPUT_REJECTED) from None
        try:
            args = [self._arg_text(arg) for arg in plan.args]  # type: ignore[attr-defined]
            cwd = folder.resolve(plan.cwd)  # type: ignore[attr-defined]
            patterns = list(plan.artifact_patterns)  # type: ignore[attr-defined]
            for pattern in patterns:
                compile_pattern(pattern)
            env = build_environment(
                env_allow=settings.env_allow,
                work_dir=str(folder.path_of("work").path),
                tmp_dir=str(folder.path_of("tmp").path),
                signal_dir=str(folder.path_of("signal").path),
                allowed_names=binding.env_names,
                extra_env=plan.extra_env,  # type: ignore[attr-defined]
            )
        except PathRejected as rejected:
            self._reject_path(rejected)
        except EnvRejected:
            journal.audit("env_name_rejected", a.job_id)
            raise _Fail(FailureReason.INPUT_REJECTED) from None
        except (TypeError, AttributeError):
            journal.audit("executor_error", a.job_id, kind="invalid_plan")
            raise _Fail(FailureReason.EXECUTOR_ERROR) from None
        spec = LaunchSpec(tool.path, args, str(cwd.path), env, tool.memory_limit_bytes)
        return _Prepared(folder, context, spec, patterns)

    def _reject_path(self, rejected: PathRejected) -> NoReturn:
        """パスの検査に落ちた入力を、件数と監査に記録して、ツールを起動せずに失敗にする。"""
        self.path_rejections += 1
        self.agent.journal.audit("path_rejected", self.assignment.job_id, kind=rejected.kind, text=rejected.detail)
        raise _Fail(FailureReason.INPUT_REJECTED) from None

    @staticmethod
    def _arg_text(arg: Arg) -> str:
        if isinstance(arg, Literal):
            if "\x00" in arg.value:
                raise TypeError
            return arg.value
        if isinstance(arg, WorkPath):
            return str(arg.path)
        raise TypeError

    async def _fetch_source(self, dest: WorkPath) -> None:
        agent, a = self.agent, self.assignment
        if agent.fetcher is None:
            raise _Fail(FailureReason.SOURCE_UNAVAILABLE)
        credential = None
        try:
            credential = await retry_unavailable(
                lambda: agent.client.source_credential(a.job_id), sleep=agent.sleep, should_stop=self.stop.is_set
            )
        except CoreRejected:
            raise _Fail(FailureReason.SOURCE_UNAVAILABLE) from None
        if credential is None:
            raise _Fail(FailureReason.SOURCE_UNAVAILABLE)
        self.secrets.append(credential.secret)  # ログのマスク(完全一致)にだけ使う。エグゼキュータ・ツールへは渡さない
        try:
            await agent.fetcher.fetch(a.source or "", a.revision, credential, dest)
        except (SourceUnavailable, OSError):
            raise _Fail(FailureReason.SOURCE_UNAVAILABLE) from None
        finally:
            credential = None  # 取得の直後に破棄する(参照を保持しない)

    async def _run_tool(self, prepared: _Prepared, executor: Executor) -> _Result:
        agent, a = self.agent, self.assignment
        settings = agent.settings
        sender = LogSender(
            agent.client,
            a.job_id,
            settings.logs,
            secrets=self.secrets,
            backlog_limit_chars=settings.state.spool_max_bytes,
            sleep=agent.sleep,
            clock=agent.clock,
        )
        sender.start()
        try:
            process = await agent.launcher.launch(prepared.spec)
        except OSError:
            summary = await sender.finish()
            self.masked_extra += summary.masked_lines
            return self._failed(FailureReason.TOOL_FAILED)
        started = agent.clock()
        pumps = [
            asyncio.create_task(self._pump(process.stdout, Stream.STDOUT, sender)),
            asyncio.create_task(self._pump(process.stderr, Stream.STDERR, sender)),
        ]
        signals = SignalWatcher(prepared.folder.path_of("signal").path, agent.client, agent.journal, a.job_id)
        stopped_by = await self._supervise(process, signals, a.timeout_seconds)
        exit_code = await _exit_code(process) if stopped_by == "none" else None
        if stopped_by == "shutdown":
            sender.abandon()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                asyncio.gather(*pumps, return_exceptions=True), timeout=settings.timeouts.stop_wait_seconds
            )
        for pump in pumps:
            pump.cancel()
        await signals.poll()
        log_summary = await sender.finish()
        close = getattr(process, "close", None)
        if close is not None:
            close()
        duration = agent.clock() - started
        if stopped_by == "abort":
            return _Result("stopped")
        if stopped_by == "lease_lost":
            return _Result("lease_lost")
        if stopped_by == "shutdown":
            return self._failed(FailureReason.AGENT_SHUTDOWN)
        if stopped_by == "timeout":
            return self._finish_report(
                Verdict(False, FailureReason.TIMEOUT),
                None,
                [],
                log_summary,
                summary_masks=0,
                truncated=log_summary.truncated,
            )
        outcome = ProcessOutcome(exit_code, stopped_by, duration, log_summary.truncated)
        return await self._conclude(prepared, executor, outcome, log_summary)

    async def _pump(self, stream: object, kind: Stream, sender: LogSender) -> None:
        async for data in stream:  # type: ignore[attr-defined]
            sender.feed(kind, data)

    async def _supervise(self, process: RunningProcess, signals: SignalWatcher, timeout_seconds: float) -> str:
        agent = self.agent
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        wait_task = asyncio.create_task(process.wait())
        waiters = {
            "abort": asyncio.create_task(self.abort.wait()),
            "lease_lost": asyncio.create_task(self.lease_lost.wait()),
            "shutdown": asyncio.create_task(self.stop.wait()),
        }
        reason = "none"
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    reason = "timeout"
                    break
                done, _ = await asyncio.wait(
                    {wait_task, *waiters.values()},
                    timeout=min(SIGNAL_POLL_SECONDS, remaining),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if wait_task in done:
                    reason = "none"
                    break
                chosen = next((name for name in ("abort", "lease_lost", "shutdown") if waiters[name] in done), None)
                if chosen is not None:
                    reason = chosen
                    break
                await signals.poll()
            if reason != "none":
                stopped = await process.terminate_tree(agent.settings.timeouts.stop_wait_seconds)
                if not stopped:
                    agent.journal.audit("stopped", self.assignment.job_id, reason="terminate_incomplete")
        finally:
            for task in waiters.values():
                task.cancel()
            await asyncio.gather(*waiters.values(), return_exceptions=True)
            if not wait_task.done():
                wait_task.cancel()
            await asyncio.gather(wait_task, return_exceptions=True)
        if reason != "none":
            agent.journal.audit("stopped", self.assignment.job_id, reason=reason)
        return reason

    async def _conclude(
        self, prepared: _Prepared, executor: Executor, outcome: ProcessOutcome, log_summary: LogSummary
    ) -> _Result:
        agent, a = self.agent, self.assignment
        try:
            verdict = executor.interpret(prepared.context, outcome)
        except Exception as exc:
            agent.journal.audit("executor_error", a.job_id, kind=type(exc).__name__)
            verdict = Verdict(False, FailureReason.EXECUTOR_ERROR)
        if not isinstance(verdict, Verdict):
            verdict = default_verdict(outcome)
        summary, summary_masks = (None, 0)
        if verdict.summary is not None:
            summary, summary_masks = mask_text(verdict.summary[:200], self.secrets, agent.settings.logs.mask_patterns)
        artifacts: list[ArtifactReference] = []
        if prepared.patterns:
            try:
                artifacts = await self._store_artifacts(prepared)
            except ArtifactLimitExceeded:
                agent.journal.audit("artifact_limit", a.job_id)
                verdict = Verdict(False, FailureReason.ARTIFACT_LIMIT_EXCEEDED)
            except ArtifactStoreError:
                verdict = Verdict(False, FailureReason.ARTIFACT_STORE_FAILED)
        return self._finish_report(
            verdict,
            outcome.exit_code,
            artifacts,
            log_summary,
            summary=summary,
            summary_masks=summary_masks,
            truncated=log_summary.truncated,
        )

    def _finish_report(
        self,
        verdict: Verdict,
        exit_code: int | None,
        artifacts: list[ArtifactReference],
        log_summary: LogSummary,
        *,
        summary: str | None = None,
        summary_masks: int = 0,
        truncated: bool = False,
    ) -> _Result:
        counters = Counters(
            self.path_rejections, self.masked_extra + log_summary.masked_lines + summary_masks, truncated
        )
        outcome = Outcome.SUCCEEDED if verdict.succeeded else Outcome.FAILED
        reason = None if verdict.succeeded else (verdict.failure_reason or FailureReason.TOOL_FAILED)
        report = FinishReport(outcome, summary, exit_code, reason, tuple(artifacts), counters)
        return _Result("report", report)

    async def _store_artifacts(self, prepared: _Prepared) -> list[ArtifactReference]:
        agent, a = self.agent, self.assignment
        store = agent.artifact_store
        if store is None:
            agent.journal.audit("artifact_store_disabled", a.job_id)
            return []  # 既定は disabled: パターンがあっても収集しない
        limits = agent.settings.artifact_store
        files = await asyncio.to_thread(
            collect,
            prepared.folder,
            prepared.patterns,
            max_files=limits.max_files,
            max_file_bytes=limits.max_file_bytes,
            max_total_bytes=limits.max_total_bytes,
        )
        references = []
        for item in files:
            references.append(await store.put(a.job_id, item.name, item.path))
        return references

    # ------------------------------------------------------------------ 報告

    async def _deliver(self, result: _Result) -> None:
        agent, a = self.agent, self.assignment
        journal, client = agent.journal, agent.client
        if result.kind == "lease_lost":
            journal.audit("stopped", a.job_id, reason="lease_lost")
            self._delivered = True
            return
        if result.kind == "stopped":
            try:
                done = await retry_unavailable(
                    lambda: client.confirm_stopped(a.job_id), sleep=agent.sleep, should_stop=self.stop.is_set
                )
                self._delivered = done is not None
            except CoreRejected as rejection:
                journal.audit("report_rejected", a.job_id, status=rejection.status, code=rejection.code or "")
                self._delivered = True
            return
        report = result.report
        assert report is not None
        if report.failure_reason is FailureReason.AGENT_SHUTDOWN:
            # 停止の信号: 最大 5 秒だけ報告を試みる。できなければ、起動時の agent_restarted(または リース切れ)に任せる
            with contextlib.suppress(Exception):
                await asyncio.wait_for(client.report_result(a.job_id, report), timeout=5)
                self._delivered = True
            return
        journal.save_result(a.job_id, report.to_json())
        try:
            done = await retry_unavailable(
                lambda: client.report_result(a.job_id, report), sleep=agent.sleep, should_stop=self.stop.is_set
            )
        except CoreRejected as rejection:
            journal.audit("report_rejected", a.job_id, status=rejection.status, code=rejection.code or "")
            done = {}
        if done is not None:
            journal.remove_result(a.job_id)
            self._delivered = True

    # ------------------------------------------------------------------ 後始末

    async def _cleanup(self) -> None:
        agent, a = self.agent, self.assignment
        self.secrets.clear()
        if self._folder is not None:
            deleted = await asyncio.to_thread(self._folder.delete)
            if not deleted:
                agent.journal.audit("work_folder_cleanup_failed", a.job_id)
            self._folder = None
        # 報告が確定した(またはリース切れなど報告しない)ときだけ、active を消す。停止の信号で未報告のときは残し、
        # 次の起動時に結果のジャーナル、または agent_restarted の失敗として報告する
        if self._delivered:
            agent.journal.clear_active()


async def _exit_code(process: RunningProcess) -> int | None:
    try:
        return await process.wait()
    except Exception:
        return None


def _seconds(value: float) -> timedelta:
    return timedelta(seconds=value)
