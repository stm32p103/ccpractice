"""評価キット自体の自己テスト用。参照実装で全部通り、全ミュータントを検出できることを確かめる。
生成役のAIには見せない（答えになるため）。"""
from datetime import date

import pytest

H = {"X-User-Id": "u1"}
H2 = {"X-User-Id": "u2"}


@pytest.fixture
def eq(seed, clock):
    clock.set(date(2026, 11, 1))
    seed("EQ-1")
    return "EQ-1"


@pytest.mark.req("REQ-001")
@pytest.mark.tc("TC-001")
def test_borrow(client, eq):
    r = client.post(f"/equipment/{eq}/loan", json={"dueDate": "2026-11-05"}, headers=H)
    assert r.status_code == 201
    assert r.json()["borrowerId"] == "u1"


@pytest.mark.req("REQ-002")
@pytest.mark.tc("TC-002")
def test_borrow_conflict(client, eq):
    client.post(f"/equipment/{eq}/loan", json={"dueDate": "2026-11-05"}, headers=H)
    r = client.post(f"/equipment/{eq}/loan", json={"dueDate": "2026-11-05"}, headers=H2)
    assert r.status_code == 409


@pytest.mark.req("REQ-003")
@pytest.mark.parametrize("due,ok", [("2026-11-01", False), ("2026-11-02", True),
                                     ("2026-11-15", True), ("2026-11-16", False)])
@pytest.mark.tc("TC-003")
def test_due_bounds(client, eq, due, ok):
    r = client.post(f"/equipment/{eq}/loan", json={"dueDate": due}, headers=H)
    assert (r.status_code == 201) == ok
    if not ok:
        assert r.status_code == 422


@pytest.mark.req("REQ-004", "REQ-007")
@pytest.mark.tc("TC-004")
def test_return_by_other_and_status(client, eq):
    client.post(f"/equipment/{eq}/loan", json={"dueDate": "2026-11-05"}, headers=H)
    r = client.post(f"/equipment/{eq}/return", headers=H2)
    assert r.status_code == 200
    s = client.get(f"/equipment/{eq}/status").json()
    assert s["state"] == "available" and s["borrowerId"] is None and s["dueDate"] is None


@pytest.mark.req("REQ-005")
@pytest.mark.tc("TC-005")
def test_return_not_loaned(client, eq):
    assert client.post(f"/equipment/{eq}/return", headers=H).status_code == 409


@pytest.mark.req("REQ-006")
@pytest.mark.tc("TC-006")
def test_unknown(client, eq):
    assert client.get("/equipment/NOPE/status").status_code == 404
    assert client.post("/equipment/NOPE/return", headers=H).status_code == 404
    assert client.post("/equipment/NOPE/loan", json={"dueDate": "2026-11-05"}, headers=H).status_code == 404


@pytest.mark.req("REQ-007")
@pytest.mark.tc("TC-007")
def test_status_on_loan(client, eq):
    client.post(f"/equipment/{eq}/loan", json={"dueDate": "2026-11-05"}, headers=H)
    r = client.get(f"/equipment/{eq}/status")
    assert r.status_code == 200
    s = r.json()
    assert s == {"equipmentId": eq, "state": "on_loan", "borrowerId": "u1", "dueDate": "2026-11-05"}


@pytest.mark.req("REQ-008")
@pytest.mark.tc("TC-008")
def test_overdue_boundary(client, eq, clock):
    client.post(f"/equipment/{eq}/loan", json={"dueDate": "2026-11-05"}, headers=H)
    clock.set(date(2026, 11, 5))
    r = client.get("/loans/overdue")
    assert r.status_code == 200
    assert r.json() == []
    clock.set(date(2026, 11, 6))
    assert [l["equipmentId"] for l in client.get("/loans/overdue").json()] == [eq]


@pytest.mark.req("REQ-009")
@pytest.mark.tc("TC-009")
def test_extend_rules(client, eq):
    client.post(f"/equipment/{eq}/loan", json={"dueDate": "2026-11-05"}, headers=H)
    assert client.post(f"/equipment/{eq}/loan/extend", json={"newDueDate": "2026-11-07"}, headers=H2).status_code == 403
    assert client.post(f"/equipment/{eq}/loan/extend", json={"newDueDate": "2026-11-13"}, headers=H).status_code == 422
    assert client.post(f"/equipment/{eq}/loan/extend", json={"newDueDate": "2026-11-12"}, headers=H).status_code == 200
    assert client.post(f"/equipment/{eq}/loan/extend", json={"newDueDate": "2026-11-13"}, headers=H).status_code == 409
