"""ランナーエージェントの主ループ(research.md R3・R13・R14。FR-001、FR-008、FR-009)。

起動 → 回復(未報告の結果、再起動で残ったジョブ、残った作業フォルダ)→ 登録 → 問い合わせ(固定の間隔 ±20%)→ 実行 → 報告。
着信は受けない。到達できない間はバックオフして再試行し、実行中のジョブは継続する。同時に実行するジョブは 1 件。
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job_runner_protocol.messages import FinishReport, ProtocolViolation
from job_runner_protocol.vocabulary import FailureReason, Outcome

from .core_client import CoreRejected, CoreUnavailable
from .execution import AgentContext, JobRun
from .guard.fs_win import is_reparse_point
from .guard.workpath import WorkFolder
from .retry import backoff_delays, retry_unavailable


class RunnerAgent:
    def __init__(self, context: AgentContext, *, rng: random.Random | None = None) -> None:
        self.ctx = context
        self._rng = rng or random.Random()
        self.jobs_run = 0

    # ------------------------------------------------------------------ 公開

    async def run(self, stop: asyncio.Event) -> None:
        await self.startup(stop)
        await self.register(stop)
        failures = backoff_delays()
        while not stop.is_set():
            outcome = await self.poll_once(stop)
            if outcome == "ran":
                failures = backoff_delays()
                continue
            delay = self._jitter(self.ctx.settings.poll_interval_seconds) if outcome == "idle" else next(failures)
            await self._sleep(delay, stop)

    async def startup(self, stop: asyncio.Event) -> None:
        """起動時の回復。未報告の結果 → 再起動で残ったジョブ → 残った作業フォルダ →
        保存先の保持期間と書き込みの検査。"""
        ctx = self.ctx
        ctx.journal.purge_old_audit()
        await self._deliver_journaled_results(stop)
        await self._report_restarted_job(stop)
        await asyncio.to_thread(self._clean_work_root)
        if ctx.artifact_store is not None:
            await ctx.artifact_store.verify_writable()
            cutoff = datetime.now(UTC) - timedelta(days=ctx.settings.artifact_store.retention_days)
            await ctx.artifact_store.purge_older_than(cutoff)

    async def register(self, stop: asyncio.Event) -> None:
        ctx = self.ctx
        delays = backoff_delays()
        while not stop.is_set():
            try:
                result = await retry_unavailable(
                    lambda: ctx.client.register(ctx.settings.capabilities),
                    sleep=ctx.sleep,
                    should_stop=stop.is_set,
                    delays=delays,
                )
            except CoreRejected:
                await self._sleep(
                    next(delays), stop
                )  # 登録の拒否(能力の申告の違反など)は、設定の修正を待って再試行する
                continue
            if result is not None:
                return

    async def poll_once(self, stop: asyncio.Event) -> str:
        """1 回の問い合わせ。'ran'(ジョブを実行した)、'idle'(割り当てなし)、'error'(到達できない・拒否)を返す。"""
        ctx = self.ctx
        if not self._has_free_space():
            return "idle"
        try:
            result = await ctx.client.request_job()
        except CoreUnavailable:
            return "error"
        except CoreRejected as rejection:
            if rejection.code == "runner_not_registered":
                await self.register(stop)
            return "error"
        if result.assignment is None:
            return "idle"
        self.jobs_run += 1
        await JobRun(ctx, result.assignment, result.heartbeat_interval_seconds, stop).run()
        return "ran"

    # ------------------------------------------------------------------ 起動時の回復

    async def _deliver_journaled_results(self, stop: asyncio.Event) -> None:
        ctx = self.ctx
        for job_id, raw in ctx.journal.load_results():
            try:
                report = FinishReport.from_json(raw)
            except ProtocolViolation:
                ctx.journal.remove_result(job_id)
                continue
            await self._report_final(job_id, report, stop)

    async def _report_final(self, job_id: str, report: FinishReport, stop: asyncio.Event) -> None:
        ctx = self.ctx
        try:
            done = await retry_unavailable(
                lambda: ctx.client.report_result(job_id, report), sleep=ctx.sleep, should_stop=stop.is_set
            )
        except CoreRejected as rejection:
            ctx.journal.audit("report_rejected", job_id, status=rejection.status, code=rejection.code or "")
            done = {}
        if done is not None:
            ctx.journal.remove_result(job_id)

    async def _report_restarted_job(self, stop: asyncio.Event) -> None:
        ctx = self.ctx
        active = ctx.journal.read_active()
        if active is None:
            return
        job_id = str(active["job_id"])
        ctx.journal.audit("agent_restarted", job_id)
        report = FinishReport(Outcome.FAILED, None, None, FailureReason.AGENT_RESTARTED)
        await self._report_final(job_id, report, stop)
        ctx.journal.clear_active()

    def _clean_work_root(self) -> None:
        root = Path(self.ctx.settings.work.root)
        if not root.is_dir():
            return
        for entry in root.iterdir():
            if is_reparse_point(entry):
                with contextlib.suppress(OSError):
                    entry.unlink() if entry.is_file() or entry.is_symlink() else entry.rmdir()
            elif entry.is_dir():
                if not WorkFolder(entry).delete():
                    self.ctx.journal.audit("work_folder_cleanup_failed")
            else:
                with contextlib.suppress(OSError):
                    entry.unlink()

    def _has_free_space(self) -> bool:
        root = Path(self.ctx.settings.work.root)
        try:
            target = root if root.exists() else root.parent
            return shutil.disk_usage(target).free >= self.ctx.settings.work.min_free_bytes
        except OSError:
            return True

    # ------------------------------------------------------------------ 補助

    def _jitter(self, seconds: float) -> float:
        return seconds * (1 + self._rng.uniform(-0.2, 0.2))

    async def _sleep(self, seconds: float, stop: asyncio.Event) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)
