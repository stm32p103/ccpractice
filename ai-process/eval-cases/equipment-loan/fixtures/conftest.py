"""テストの土台（生成役と評価役の約束事）。

生成されるテストは、このファイルが提供するフィクスチャだけを使う。
- client : 契約どおりのAPIに対する HTTP クライアント（httpx互換。fastapi.testclient.TestClient）
- clock  : 「今日」を設定する。clock.set(date(2026, 11, 1))。初期値は 2026-11-01
- seed   : 備品を登録する。seed("EQ-1", "プロジェクター")（備品登録APIは無いのでこれを使う）

各テストには @pytest.mark.req("REQ-xxx") と @pytest.mark.tc("TC-xxx") を付け、
どの要件の、テストケース一覧のどのケースを確かめるテストかを示す（どちらも複数可）。
このファイルは評価時に評価キット側のものに差し替えられる。編集しても反映されない。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def pytest_configure(config):
    config.addinivalue_line("markers", "req(*ids): このテストが確かめる要件ID")
    config.addinivalue_line("markers", "tc(*ids): このテストが実装するテストケースID（test-cases.yaml）")


@pytest.fixture
def _app():
    return create_app()


@pytest.fixture
def client(_app):
    return TestClient(_app)


class _Clock:
    def __init__(self, store):
        self._store = store

    def set(self, d: date) -> None:
        self._store.today = d

    @property
    def today(self) -> date:
        return self._store.today


@pytest.fixture
def clock(_app):
    return _Clock(_app.state.store)


@pytest.fixture
def seed(_app):
    def _seed(equipment_id: str, name: str = "備品") -> None:
        _app.state.store.equipment[equipment_id] = name
    return _seed
