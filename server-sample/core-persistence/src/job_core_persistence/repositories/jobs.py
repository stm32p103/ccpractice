"""ジョブと待機列のリポジトリ(contracts/ports.md「JobRepository」「QueueRepository」)。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from job_core.job.application.ports import JobSearchCriteria, Page
from job_core.job.application.search_cursor import decode_search_cursor, encode_search_cursor
from job_core.job.domain.errors import ValidationFailed
from job_core.job.domain.job import Job
from job_core.job.domain.queue import DEFAULT_QUEUE_ID, Queue
from job_core.job.domain.states import TERMINAL_STATES, JobState
from job_core.job.domain.values import DuplicateKey
from job_core.shared.ids import JobId, RunnerId

from ..codec import decode, encode
from ..models import jobs, queue
from ..tracking import Singleton, Tracked

TERMINAL_VALUES = [s.value for s in TERMINAL_STATES]


def _duplicate_key_text(key: DuplicateKey | None) -> str | None:
    return None if key is None else json.dumps(encode(key), sort_keys=True)


def _row_of(job: Job) -> dict[str, Any]:
    return {
        "state": job.state.value,
        "owner": job.submitter.owner,
        "submitted_at": job.submitted_at,
        "finished_at": job.finished_at,
        "assigned_runner_id": job.assigned_runner_id,
        "retry_of": job.retry_of,
        "duplicate_key": _duplicate_key_text(job.definition.duplicate_key()),
    }


def parse_offset(cursor: str | None) -> int:
    try:
        start = int(cursor) if cursor else 0
    except ValueError:
        raise ValidationFailed("cursor", "不正な cursor") from None
    if start < 0:
        raise ValidationFailed("cursor", "不正な cursor")
    return start


class SqlJobRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.tracked = Tracked[Job](engine, jobs, "job_id", Job, _row_of, "ジョブ")
        self.delete_cutoffs: list[datetime] = []

    def get(self, job_id: JobId) -> Job | None:
        return self.tracked.load(job_id)

    def exists(self, job_id: JobId) -> bool:
        return self.tracked.exists(job_id)

    def add(self, job: Job) -> None:
        self.tracked.add(job.job_id, job)

    def save(self, job: Job) -> None:
        self.tracked.save(job.job_id, job)

    def find_queued_by_duplicate_key(self, key: DuplicateKey) -> Job | None:
        text = _duplicate_key_text(key)
        found = self.tracked.query(
            sa.and_(jobs.c.state == JobState.QUEUED.value, jobs.c.duplicate_key == text),
            lambda j: j.state is JobState.QUEUED and j.definition.duplicate_key() == key,
        )
        return found[0] if found else None

    def find_unfinished_by_runner(self, runner_id: RunnerId) -> Job | None:
        found = self.tracked.query(
            sa.and_(jobs.c.assigned_runner_id == runner_id, jobs.c.state.not_in(TERMINAL_VALUES)),
            lambda j: j.assigned_runner_id == runner_id and not j.state.is_terminal,
        )
        return found[0] if found else None

    def find_retries_of(self, job_id: JobId) -> list[JobId]:
        found = self.tracked.query(jobs.c.retry_of == job_id, lambda j: j.retry_of == job_id, track=False)
        return [j.job_id for j in sorted(found, key=lambda j: (j.submitted_at, j.job_id))]

    def list_by_states(self, states: Any, cursor: str | None, limit: int | None) -> Page[Job]:
        wanted = set(states)
        values = [s.value for s in wanted]
        terminal_only = wanted <= TERMINAL_STATES
        start = parse_offset(cursor)
        where = jobs.c.state.in_(values)
        if terminal_only:
            order = [sa.func.coalesce(jobs.c.finished_at, jobs.c.submitted_at).desc(), jobs.c.job_id.desc()]
        else:
            order = [jobs.c.submitted_at.asc(), jobs.c.job_id.asc()]
        if not self.tracked.pending:
            stmt = sa.select(jobs.c.doc, jobs.c.version).where(where).order_by(*order).offset(start)
            if limit is not None:
                stmt = stmt.limit(limit + 1)
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).all()
            items = [self.tracked._decode(r) for r in rows]
            if limit is not None and len(items) > limit:
                return Page(items[:limit], str(start + limit))
            return Page(items, None)
        found = self.tracked.query(where, lambda j: j.state in wanted, track=False)
        if terminal_only:
            found.sort(key=lambda j: (j.finished_at or j.submitted_at, j.job_id), reverse=True)
        else:
            found.sort(key=lambda j: (j.submitted_at, j.job_id))
        if limit is None:
            return Page(found[start:], None)
        end = start + limit
        return Page(found[start:end], str(end) if end < len(found) else None)

    def search(self, criteria: JobSearchCriteria, cursor: str | None, limit: int) -> Page[Job]:
        if limit < 1:
            raise ValueError("limit は 1 以上")
        conditions: list[sa.ColumnElement[bool]] = []
        if criteria.states is not None:
            conditions.append(jobs.c.state.in_([s.value for s in criteria.states]))
        if criteria.owner is not None:
            conditions.append(jobs.c.owner == criteria.owner)
        if criteria.submitted_from is not None:
            conditions.append(jobs.c.submitted_at >= criteria.submitted_from)
        if criteria.submitted_to is not None:
            conditions.append(jobs.c.submitted_at < criteria.submitted_to)
        if cursor is not None:
            at, job_id = decode_search_cursor(cursor)
            conditions.append(sa.tuple_(jobs.c.submitted_at, jobs.c.job_id) < sa.tuple_(at, job_id))
        stmt = (
            sa.select(jobs.c.doc, jobs.c.version)
            .where(*conditions)
            .order_by(jobs.c.submitted_at.desc(), jobs.c.job_id.desc())
            .limit(limit + 1)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
        items = [self.tracked._decode(r) for r in rows]
        if len(items) > limit:
            last = items[limit - 1]
            return Page(items[:limit], encode_search_cursor(last.submitted_at, last.job_id))
        return Page(items, None)

    def delete_finished_before(self, cutoff: datetime) -> int:
        with self._engine.connect() as conn:
            count = conn.execute(
                sa.select(sa.func.count())
                .select_from(jobs)
                .where(jobs.c.state.in_(TERMINAL_VALUES), jobs.c.finished_at < cutoff)
            ).scalar_one()
        self.delete_cutoffs.append(cutoff)
        return int(count)


class SqlQueueRepository:
    def __init__(self, engine: Engine) -> None:
        self.singleton = Singleton[Queue](engine, queue, "queue_id", DEFAULT_QUEUE_ID, Queue, Queue, "待機列")

    def get(self) -> Queue:
        return self.singleton.get()

    def save(self, queue_: Queue) -> None:
        self.singleton.save(queue_)


__all__ = ["SqlJobRepository", "SqlQueueRepository", "decode", "parse_offset"]
