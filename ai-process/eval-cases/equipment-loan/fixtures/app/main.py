"""参照実装（openapi_v2.yaml 準拠、インメモリ）。

評価専用。生成されたテストの「正しさ」を確かめるために使う。
環境変数 MUTANT にミュータント名を入れると、わざと1か所だけ壊れた動きになる。
生成役のAIにはこのディレクトリを見せないこと（答えが漏れるため）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ミュータント一覧: 名前 -> (壊す要件, 対象の版, 内容)
MUTANTS = {
    "m01_no_conflict_check":   ("REQ-002", "v1", "貸出中でも借りられてしまう"),
    "m02_due_upper_15":        ("REQ-003", "v1", "返却予定日の上限が15日になっている"),
    "m03_due_same_day_ok":     ("REQ-003", "v1", "当日を返却予定日にできてしまう"),
    "m04_return_not_loaned_ok":("REQ-005", "v1", "貸出中でない備品を返却しても200"),
    "m05_status_unknown_200":  ("REQ-006", "v1", "存在しない備品の状態参照が200"),
    "m06_overdue_includes_due":("REQ-008", "v1", "返却予定日当日も延滞に含める"),
    "m07_status_keeps_borrower":("REQ-007","v1", "返却後も借りた人が残る"),
    "m08_extend_twice":        ("REQ-009", "v2", "2回目の延長もできてしまう"),
    "m09_extend_by_other":     ("REQ-009", "v2", "本人以外も延長できてしまう"),
    "m10_extend_upper_8":      ("REQ-009", "v2", "延長の上限が8日になっている"),
}


@dataclass
class Loan:
    equipment_id: str
    borrower_id: str
    loan_date: date
    due_date: date
    extended: bool = False

    def to_json(self) -> dict:
        return {"equipmentId": self.equipment_id, "borrowerId": self.borrower_id,
                "loanDate": self.loan_date.isoformat(), "dueDate": self.due_date.isoformat()}


@dataclass
class Store:
    equipment: dict[str, str] = field(default_factory=dict)   # id -> name
    loans: dict[str, Loan] = field(default_factory=dict)      # 貸出中のみ。key = equipment id
    last_borrower: dict[str, str] = field(default_factory=dict)
    today: date = date(2026, 11, 1)


class BorrowBody(BaseModel):
    dueDate: date


class ExtendBody(BaseModel):
    newDueDate: date


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def create_app(mutant: Optional[str] = None) -> FastAPI:
    mutant = mutant if mutant is not None else os.environ.get("MUTANT") or None
    if mutant and mutant not in MUTANTS:
        raise ValueError(f"unknown mutant: {mutant}")
    m = lambda name: mutant == name  # noqa: E731

    app = FastAPI(title="備品貸出API（参照実装）")
    store = Store()
    app.state.store = store

    @app.exception_handler(HTTPException)
    async def _handler(_req, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    def require(eid: str) -> None:
        if eid not in store.equipment:
            raise _err(404, "not_found", f"equipment {eid} not found")

    def status_json(eid: str) -> dict:
        loan = store.loans.get(eid)
        if loan:
            return {"equipmentId": eid, "state": "on_loan",
                    "borrowerId": loan.borrower_id, "dueDate": loan.due_date.isoformat()}
        borrower = store.last_borrower.get(eid) if m("m07_status_keeps_borrower") else None
        return {"equipmentId": eid, "state": "available", "borrowerId": borrower, "dueDate": None}

    @app.post("/equipment/{equipmentId}/loan", status_code=201)
    def borrow(equipmentId: str, body: BorrowBody, x_user_id: str = Header(...)):
        require(equipmentId)
        if equipmentId in store.loans and not m("m01_no_conflict_check"):
            raise _err(409, "already_on_loan", "equipment is on loan")
        today = store.today
        upper = 15 if m("m02_due_upper_15") else 14
        lower = 0 if m("m03_due_same_day_ok") else 1
        if not (today + timedelta(days=lower) <= body.dueDate <= today + timedelta(days=upper)):
            raise _err(422, "invalid_due_date", "dueDate out of range")
        loan = Loan(equipmentId, x_user_id, today, body.dueDate)
        store.loans[equipmentId] = loan
        store.last_borrower[equipmentId] = x_user_id
        return loan.to_json()

    @app.post("/equipment/{equipmentId}/return")
    def return_(equipmentId: str, x_user_id: str = Header(...)):
        require(equipmentId)
        if equipmentId not in store.loans:
            if m("m04_return_not_loaned_ok"):
                return status_json(equipmentId)
            raise _err(409, "not_on_loan", "equipment is not on loan")
        del store.loans[equipmentId]
        return status_json(equipmentId)

    @app.post("/equipment/{equipmentId}/loan/extend")
    def extend(equipmentId: str, body: ExtendBody, x_user_id: str = Header(...)):
        require(equipmentId)
        loan = store.loans.get(equipmentId)
        if loan is None:
            raise _err(409, "not_on_loan", "equipment is not on loan")
        if loan.borrower_id != x_user_id and not m("m09_extend_by_other"):
            raise _err(403, "not_borrower", "only the borrower can extend")
        if loan.extended and not m("m08_extend_twice"):
            raise _err(409, "already_extended", "loan already extended")
        upper = 8 if m("m10_extend_upper_8") else 7
        if not (loan.due_date + timedelta(days=1) <= body.newDueDate <= loan.due_date + timedelta(days=upper)):
            raise _err(422, "invalid_due_date", "newDueDate out of range")
        loan.due_date = body.newDueDate
        loan.extended = True
        return loan.to_json()

    @app.get("/equipment/{equipmentId}/status")
    def get_status(equipmentId: str):
        if m("m05_status_unknown_200") and equipmentId not in store.equipment:
            return {"equipmentId": equipmentId, "state": "available", "borrowerId": None, "dueDate": None}
        require(equipmentId)
        return status_json(equipmentId)

    @app.get("/loans/overdue")
    def overdue():
        today = store.today
        if m("m06_overdue_includes_due"):
            items = [l for l in store.loans.values() if l.due_date <= today]
        else:
            items = [l for l in store.loans.values() if l.due_date < today]
        return [l.to_json() for l in items]

    return app
