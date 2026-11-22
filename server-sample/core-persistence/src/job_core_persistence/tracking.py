"""楽観的排他つきの追跡(UoW ごとの読み込み・追加・保存と、commit での検査・反映)。

メモリ上の Fake(`job_testing.core_fakes`)と同じ約束を、PostgreSQL の行に対して実現する。
- 読み込んだ集約は複製して追跡し、commit で変更があれば `version` を条件に UPDATE する(0 行なら ConcurrencyConflict)。
- 変更のない集約も、`SELECT ... FOR SHARE` で version を確かめる(同時の更新を検出し、commit まで更新を待たせる)。
- 追加は INSERT。一意性の違反(同名・重複)は ConcurrencyConflict にする。UPDATE を先に、INSERT を後に行う
  (リースの終了と新しいリースの作成のように、同じ UoW の中で一意の索引を空けてから使うため)。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from job_core.job.domain.errors import ConcurrencyConflict

from .codec import decode, encode


def snapshot(obj: Any) -> dict[str, Any]:
    """version 以外の全項目(集約が変更されたかの比較に使う)。"""
    body = encode(obj)
    body.pop("version", None)
    return body  # type: ignore[no-any-return]


def to_conflict(error: DBAPIError, label: str) -> ConcurrencyConflict:
    """一意性の違反・デッドロック・直列化の失敗を、同時の更新の衝突として扱う。"""
    return ConcurrencyConflict(f"{label} が同時に更新された")


class Versioned(Protocol):
    version: int


class Tracked[T: Versioned]:
    def __init__(
        self,
        engine: Engine,
        table: sa.Table,
        key: str,
        cls: type[T],
        row_of: Callable[[T], dict[str, Any]],
        label: str,
    ) -> None:
        self.engine = engine
        self.table = table
        self.key = key
        self.cls = cls
        self.row_of = row_of
        self.label = label
        self.pending: dict[str, T] = {}
        self.loaded: dict[str, tuple[int, dict[str, Any]]] = {}
        self.new_keys: set[str] = set()

    # 読み込み ---------------------------------------------------------------

    def _decode(self, row: Any) -> T:
        obj: T = decode(self.cls, row.doc)
        obj.version = row.version
        return obj

    def _track(self, key: str, obj: T, version: int) -> T:
        self.loaded[key] = (version, snapshot(obj))
        self.pending[key] = obj
        return obj

    def load(self, key: str) -> T | None:
        if key in self.pending:
            return self.pending[key]
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(self.table.c.doc, self.table.c.version).where(self.table.c[self.key] == key)
            ).first()
        if row is None:
            return None
        return self._track(key, self._decode(row), row.version)

    def exists(self, key: str) -> bool:
        if key in self.pending:
            return True
        with self.engine.connect() as conn:
            return conn.execute(sa.select(sa.literal(1)).where(self.table.c[self.key] == key)).first() is not None

    def query(
        self,
        where: sa.ColumnElement[bool],
        predicate: Callable[[T], bool],
        *,
        track: bool = True,
        order_by: list[Any] | None = None,
    ) -> list[T]:
        """DB の行(where)に、この UoW の変更を重ねた結果。predicate は、重ねた状態の判定(Python)。"""
        stmt = sa.select(self.table.c[self.key], self.table.c.doc, self.table.c.version).where(where)
        if order_by:
            stmt = stmt.order_by(*order_by)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).all()
        found: dict[str, T] = {}
        for row in rows:
            key = getattr(row, self.key)
            if key in self.pending:
                continue
            obj = self._decode(row)
            if not predicate(obj):
                continue
            found[key] = self._track(key, obj, row.version) if track else obj
        for key, obj in self.pending.items():
            if predicate(obj):
                found[key] = obj
        return list(found.values())

    # 変更 -------------------------------------------------------------------

    def add(self, key: str, obj: T) -> None:
        if self.exists(key):
            raise ValueError(f"{key} は既にある")
        self.pending[key] = obj
        self.new_keys.add(key)

    def save(self, key: str, obj: T) -> None:
        if key not in self.pending:
            raise ValueError("save は、この UoW で読み込んだか追加した集約にだけ使う")
        self.pending[key] = obj

    # commit ----------------------------------------------------------------

    def apply(self, conn: Connection) -> None:
        t = self.table
        inserts: list[tuple[str, T]] = []
        for key in sorted(self.pending):
            obj = self.pending[key]
            if key in self.new_keys:
                inserts.append((key, obj))
                continue
            loaded_version, before = self.loaded[key]
            if snapshot(obj) == before:
                current = conn.execute(
                    sa.select(t.c.version).where(t.c[self.key] == key).with_for_update(read=True)
                ).scalar_one_or_none()
                if current != loaded_version:
                    raise ConcurrencyConflict(f"{self.label} {key} が同時に更新された")
                continue
            obj.version = loaded_version + 1
            values = {**self.row_of(obj), "version": obj.version, "doc": encode(obj)}
            result = conn.execute(
                sa.update(t).where(t.c[self.key] == key, t.c.version == loaded_version).values(**values)
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict(f"{self.label} {key} が同時に更新された")
        for key, obj in inserts:
            obj.version += 1
            conn.execute(
                sa.insert(t).values(
                    **{self.key: key},
                    **self.row_of(obj),
                    version=obj.version,
                    doc=encode(obj),
                )
            )


class Singleton[T: Versioned]:
    """1 行だけの集約(待機列・許可リスト)。行がなければ既定の値(version 0)から始める。"""

    def __init__(
        self,
        engine: Engine,
        table: sa.Table,
        key_column: str,
        key: str,
        cls: type[T],
        factory: Callable[[], T],
        label: str,
    ) -> None:
        self.engine, self.table, self.key_column, self.key = engine, table, key_column, key
        self.cls, self.factory, self.label = cls, factory, label
        self.pending: T | None = None
        self.loaded_version: int | None = None
        self.before: dict[str, Any] | None = None
        self.existed = False

    def get(self) -> T:
        if self.pending is None:
            with self.engine.connect() as conn:
                row = conn.execute(
                    sa.select(self.table.c.doc, self.table.c.version).where(self.table.c[self.key_column] == self.key)
                ).first()
            if row is None:
                self.pending = self.factory()
                self.loaded_version = 0
            else:
                self.pending = decode(self.cls, row.doc)
                self.pending.version = row.version
                self.loaded_version = row.version
                self.existed = True
            self.before = snapshot(self.pending)
        return self.pending

    def save(self, obj: T) -> None:
        if self.pending is None or obj is not self.pending:
            raise ValueError("save は、この UoW で get した集約にだけ使う")

    def apply(self, conn: Connection) -> None:
        if self.pending is None or self.loaded_version is None or self.before is None:
            return
        t = self.table
        where = t.c[self.key_column] == self.key
        if snapshot(self.pending) == self.before:
            if self.existed:
                current = conn.execute(
                    sa.select(t.c.version).where(where).with_for_update(read=True)
                ).scalar_one_or_none()
                if current != self.loaded_version:
                    raise ConcurrencyConflict(f"{self.label}が同時に更新された")
            return
        self.pending.version = self.loaded_version + 1
        doc = encode(self.pending)
        if self.existed:
            result = conn.execute(
                sa.update(t)
                .where(where, t.c.version == self.loaded_version)
                .values(version=self.pending.version, doc=doc)
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict(f"{self.label}が同時に更新された")
        else:
            conn.execute(sa.insert(t).values(**{self.key_column: self.key}, version=self.pending.version, doc=doc))


def run_commit(engine: Engine, action: Callable[[Connection], None]) -> None:
    """1 つのトランザクションで action を実行する。一意性の違反・デッドロックは ConcurrencyConflict。"""
    try:
        with engine.begin() as conn:
            action(conn)
    except IntegrityError as error:
        raise to_conflict(error, "データ") from error
    except DBAPIError as error:
        sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
        if sqlstate in {"40001", "40P01"}:  # 直列化の失敗、デッドロック
            raise to_conflict(error, "データ") from error
        raise
