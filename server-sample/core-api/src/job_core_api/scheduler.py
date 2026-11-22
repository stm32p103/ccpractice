"""定期処理(research.md R20)。

API のプロセスの中の背景のスレッドが、固定の主体(`SYSTEM`。権限は `runner.sweep` と `retention.purge` だけ)で、
ランナーの定期処理(30 秒ごと)、保持期間の削除(1 日 1 回)、期限切れ・失効後のセッションの削除と認証失敗の窓の確定を
行う。HTTP からは呼べない。プロセスが 1 つである前提(複数のプロセスでは重複して動く)。
結果は、通知(ランナーの offline 化、待機列の変化)にも載せる。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from job_core.access.permission import Permission
from job_core.access.principal import Principal, PrincipalKind

from .deps import ApiDependencies

logger = logging.getLogger("job_core_api.scheduler")

SYSTEM_PRINCIPAL = Principal.of(
    "system:scheduler", [Permission.RUNNER_SWEEP, Permission.RETENTION_PURGE], PrincipalKind.SYSTEM
)
"""定期処理の主体。権限はこの 2 つだけ(ランナー・ジョブの管理や閲覧の権限は持たない)。"""

SWEEP_INTERVAL = timedelta(seconds=30)
PURGE_INTERVAL = timedelta(days=1)
SESSION_CLEANUP_INTERVAL = timedelta(hours=1)


class Scheduler:
    def __init__(
        self,
        deps: ApiDependencies,
        *,
        sweep_interval: timedelta = SWEEP_INTERVAL,
        purge_interval: timedelta = PURGE_INTERVAL,
        session_cleanup_interval: timedelta = SESSION_CLEANUP_INTERVAL,
        poll_seconds: float = 1.0,
    ) -> None:
        self._deps = deps
        self._clock = deps.core.deps.clock
        self._poll_seconds = poll_seconds
        self._next: dict[str, datetime] = {}
        self._intervals = {
            "sweep": sweep_interval,
            "purge": purge_interval,
            "sessions": session_cleanup_interval,
        }
        self._tasks: dict[str, Callable[[], None]] = {
            "sweep": self.run_sweep,
            "purge": self.run_purge,
            "sessions": self.run_session_cleanup,
        }
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # 個々の処理(冪等)-------------------------------------------------------

    def run_sweep(self) -> None:
        core = self._deps.core
        result = core.sweep_runners(SYSTEM_PRINCIPAL)
        publisher = self._deps.publisher
        publisher.runner_event()  # offline 化などの状態の変化を、一覧との差分から発行する
        if result.leases_expired or result.leases_ended:
            publisher.queue_changed()

    def run_purge(self) -> None:
        self._deps.core.purge(SYSTEM_PRINCIPAL)

    def run_session_cleanup(self) -> None:
        cutoff = self._clock.now() - self._deps.settings.session_retention
        self._deps.sessions.delete_inactive_before(cutoff)
        self._deps.auditor.flush()

    # 実行 -------------------------------------------------------------------

    def tick(self) -> list[str]:
        """期限の来た処理を実行する。実行した処理の名前を返す。失敗しても他の処理は続ける。"""
        now = self._clock.now()
        ran: list[str] = []
        with self._lock:
            for name, task in self._tasks.items():
                due = self._next.get(name)
                if due is not None and now < due:
                    continue
                self._next[name] = now + self._intervals[name]
                try:
                    task()
                    ran.append(name)
                except Exception:
                    logger.exception("scheduled task failed: %s", name)
        return ran

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="job-core-api-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._poll_seconds)
