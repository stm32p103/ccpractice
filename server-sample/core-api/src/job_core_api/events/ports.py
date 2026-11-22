"""変更の通知のポート(contracts/ports.md「ChangeBroker」、contracts/change-event.schema.json)。

通知は自由な文字列の項目を持たない(T-A8)。語彙は固定の列挙で表す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ChangeType(StrEnum):
    JOB_CHANGED = "job.changed"
    RUNNER_CHANGED = "runner.changed"
    QUEUE_CHANGED = "queue.changed"
    RESYNC = "resync"
    AUTH_EXPIRED = "auth.expired"


class SubjectKind(StrEnum):
    JOB = "job"
    RUNNER = "runner"


class ChangeKind(StrEnum):
    SUBMITTED = "submitted"
    RESCHEDULED = "rescheduled"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    RETRIED = "retried"
    CREATED = "created"
    REGISTERED = "registered"
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE_CHANGED = "maintenance_changed"
    FAULT_CHANGED = "fault_changed"
    DELETED = "deleted"
    LEASE_EXPIRED = "lease_expired"


@dataclass(frozen=True)
class ChangeSubject:
    kind: SubjectKind
    id: str


_STATE = re.compile(r"^[a-z][a-z_]{0,31}$")
MAX_SUBJECT_ID = 128


@dataclass(frozen=True)
class PendingChange:
    """発行する通知(seq・epoch・日時は ChangeBroker が付ける)。型で項目を固定する。

    自由な文字列の項目を持たない(T-A8): type・change は列挙、subject は種類(列挙)と識別子、state は
    状態名(小文字と `_` だけの短い語彙)に限る。理由・説明・payload を載せる場所がない。
    """

    type: ChangeType
    subject: ChangeSubject | None = None
    state: str | None = None
    change: ChangeKind | None = None

    def __post_init__(self) -> None:
        if self.state is not None and not _STATE.match(self.state):
            raise ValueError("state は状態名の語彙(小文字と _ だけ)でなければならない")
        if self.subject is not None and not 1 <= len(self.subject.id) <= MAX_SUBJECT_ID:
            raise ValueError("subject.id は 1〜128 文字でなければならない")


@dataclass(frozen=True)
class ChangeEvent:
    """配信する通知(ChangeEvent.seq、.epoch、.type、.occurred_at、.subject、.state、.change)。"""

    seq: int
    epoch: str
    type: ChangeType
    occurred_at: datetime
    subject: ChangeSubject | None = None
    state: str | None = None
    change: ChangeKind | None = None

    @property
    def event_id(self) -> str:
        return f"{self.epoch}:{self.seq}"


class Subscription(Protocol):
    """購読。通知を順に受け取る。閉じられた(切断・購読の解除・送信待ちの超過)後は、残りを渡したら None を返す。"""

    def next(self, timeout: float) -> ChangeEvent | None:
        """次の通知を返す。timeout 秒の間に来なければ None(closed で閉じられたかを区別する)。"""
        ...

    async def next_async(self, timeout: float) -> ChangeEvent | None:
        """next の非同期版(SSE の配信用。スレッドを占有しない)。"""
        ...

    @property
    def closed(self) -> bool: ...

    def close(self) -> None: ...


class ChangeBroker(Protocol):
    @property
    def epoch(self) -> str: ...

    @property
    def last_seq(self) -> int:
        """この世代で最後に発行した通知の番号(まだなければ 0)。"""
        ...

    def publish(self, change: PendingChange) -> None:
        """呼び出しをブロックしない。購読者が遅ければ、その購読者を切断対象にする。"""
        ...

    def subscribe(self, last_event_id: str | None, topics: frozenset[str]) -> Subscription:
        """last_event_id が範囲内なら続きから。範囲外・世代違い・不正な値なら最初に resync。None なら新しい通知から。"""
        ...
