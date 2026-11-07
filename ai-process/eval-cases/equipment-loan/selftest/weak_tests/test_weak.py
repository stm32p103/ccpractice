"""評価キット自体の自己テスト用。「通るが弱い」テストの例（正常系だけ）。
検出率が低く出ることを確かめる。"""
from datetime import date

import pytest


@pytest.mark.req("REQ-001")
def test_borrow(client, seed, clock):
    clock.set(date(2026, 11, 1))
    seed("EQ-1")
    r = client.post("/equipment/EQ-1/loan", json={"dueDate": "2026-11-05"}, headers={"X-User-Id": "u1"})
    assert r.status_code == 201


@pytest.mark.req("REQ-007")
def test_status(client, seed):
    seed("EQ-1")
    assert client.get("/equipment/EQ-1/status").status_code == 200
