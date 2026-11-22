"""通知の組み立て(research.md R9)。

状態を変えるユースケースの**成功後**に、結果から PendingChange を作って ChangeBroker に載せる(コアは変えない)。
失敗・拒否は発行しない。発行に失敗しても、ユースケースの結果(コアの状態)は変わらない(通知は再取得で補える)。
ランナーの状態の変化は、一覧(状態の写し)との差分から導く(定期処理の offline 化も同じ経路)。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping

from job_core.job.application import CancelResult, FinishResult

from .ports import ChangeBroker, ChangeKind, ChangeSubject, ChangeType, PendingChange, SubjectKind

logger = logging.getLogger("job_core_api.events")

RunnerStates = Callable[[], Mapping[str, str]]

# 状態を変える操作(operation_id)→ 発行する通知の型。contracts/http-api.md の操作を網羅する(テストで検査)。
PUBLISHES: dict[str, tuple[ChangeType, ...]] = {
    "submit_job": (ChangeType.JOB_CHANGED, ChangeType.QUEUE_CHANGED),
    "retry_job": (ChangeType.JOB_CHANGED, ChangeType.QUEUE_CHANGED),
    "reschedule_job": (ChangeType.JOB_CHANGED, ChangeType.QUEUE_CHANGED),
    "cancel_job": (ChangeType.JOB_CHANGED, ChangeType.QUEUE_CHANGED),
    "create_runner": (ChangeType.RUNNER_CHANGED,),
    "set_runner_maintenance": (ChangeType.RUNNER_CHANGED,),
    "clear_runner_maintenance": (ChangeType.RUNNER_CHANGED,),
    "clear_runner_fault": (ChangeType.RUNNER_CHANGED,),
    "delete_runner": (ChangeType.RUNNER_CHANGED,),
    "reissue_runner_token": (),
    "revoke_runner_token": (),
    "runner_register": (ChangeType.RUNNER_CHANGED,),
    "runner_heartbeat": (ChangeType.RUNNER_CHANGED,),
    "runner_report_fault": (ChangeType.RUNNER_CHANGED,),
    "runner_report_recovered": (ChangeType.RUNNER_CHANGED,),
    "runner_request_job": (ChangeType.JOB_CHANGED, ChangeType.QUEUE_CHANGED, ChangeType.RUNNER_CHANGED),
    "runner_report_finished": (ChangeType.JOB_CHANGED, ChangeType.RUNNER_CHANGED),
    "runner_confirm_stopped": (ChangeType.JOB_CHANGED, ChangeType.RUNNER_CHANGED),
}
# 通知の対象外の操作(ジョブ・ランナー・待機列の状態を変えない)。理由つき。
NO_PUBLISH: dict[str, str] = {
    "replace_capability_allowlist": "許可リストの変更。ジョブ・ランナーの状態を変えない",
    "issue_service_credential": "認証情報の管理",
    "revoke_service_credential": "認証情報の管理",
    "reload_access_config": "アクセス設定の管理",
    "revoke_sessions_of": "セッションの管理",
    "login": "ログイン前の操作",
    "logout": "セッションの管理",
}

_RUNNER_CHANGE_BY_STATE: dict[str, ChangeKind] = {
    "online": ChangeKind.ONLINE,
    "offline": ChangeKind.OFFLINE,
    "maintenance": ChangeKind.MAINTENANCE_CHANGED,
    "fault": ChangeKind.FAULT_CHANGED,
    "deleted": ChangeKind.DELETED,
}


class ChangePublisher:
    def __init__(self, broker: ChangeBroker, runner_states: RunnerStates) -> None:
        self._broker = broker
        self._runner_states = runner_states
        self._known: dict[str, str] = {}
        self._lock = threading.Lock()
        self._safely(self._prime)

    # ジョブ -----------------------------------------------------------------

    def job_submitted(self, job_id: str) -> None:
        self._job(job_id, "queued", ChangeKind.SUBMITTED, queue=True)

    def job_retried(self, new_job_id: str) -> None:
        self._job(new_job_id, "queued", ChangeKind.RETRIED, queue=True)

    def job_rescheduled(self, job_id: str) -> None:
        self._job(job_id, "queued", ChangeKind.RESCHEDULED, queue=True)

    def job_cancelled(self, result: CancelResult) -> None:
        if result.abort_pending:
            self._job(result.job_id, result.state.value, ChangeKind.CANCEL_REQUESTED, queue=False)
        else:
            self._job(result.job_id, result.state.value, ChangeKind.CANCELLED, queue=True)

    def job_assigned(self, job_id: str) -> None:
        self._job(job_id, "running", ChangeKind.ASSIGNED, queue=True)

    def job_finished(self, result: FinishResult) -> None:
        kind = ChangeKind.CANCELLED if result.state.value == "cancelled" else ChangeKind.COMPLETED
        self._job(result.job_id, result.state.value, kind, queue=False)

    def queue_changed(self) -> None:
        self._safely(lambda: self._broker.publish(PendingChange(ChangeType.QUEUE_CHANGED)))

    # ランナー ---------------------------------------------------------------

    def runner_event(self, runner_id: str | None = None, hint: ChangeKind | None = None) -> None:
        """ランナーの状態を再取得し、変化した分を発行する。hint のランナーは、状態が同じでも発行する。"""
        self._safely(lambda: self._refresh_runners(runner_id, hint))

    # 内部 -------------------------------------------------------------------

    def _job(self, job_id: str, state: str, change: ChangeKind, *, queue: bool) -> None:
        def publish() -> None:
            subject = ChangeSubject(SubjectKind.JOB, str(job_id))
            self._broker.publish(PendingChange(ChangeType.JOB_CHANGED, subject, state, change))
            if queue:
                self._broker.publish(PendingChange(ChangeType.QUEUE_CHANGED))

        self._safely(publish)

    def _prime(self) -> None:
        self._known = dict(self._runner_states())

    def _refresh_runners(self, runner_id: str | None, hint: ChangeKind | None) -> None:
        with self._lock:
            current = dict(self._runner_states())
            events: list[tuple[str, str, ChangeKind]] = []
            for known_id, state in current.items():
                previous = self._known.get(known_id)
                explicit = hint if known_id == runner_id else None
                if previous is None:
                    events.append((known_id, state, explicit or ChangeKind.CREATED))
                elif previous != state or explicit is not None:
                    events.append((known_id, state, explicit or _RUNNER_CHANGE_BY_STATE.get(state, ChangeKind.ONLINE)))
            events += [(gone, "deleted", ChangeKind.DELETED) for gone in self._known if gone not in current]
            self._known = current
        for changed_id, state, change in events:
            subject = ChangeSubject(SubjectKind.RUNNER, changed_id)
            self._broker.publish(PendingChange(ChangeType.RUNNER_CHANGED, subject, state, change))

    @staticmethod
    def _safely(action: Callable[[], None]) -> None:
        try:
            action()
        except Exception:
            # 通知の失敗でユースケースの結果は変えない(クライアントは再取得で補える)
            logger.exception("failed to publish a change event")
