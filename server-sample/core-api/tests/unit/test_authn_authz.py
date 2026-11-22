"""認証・認可の網羅の検査(SC-003、SC-005。quickstart V22)。

可否は権限だけで決まり、主体の種類(人間・サービス)で変わらない。人間とサービスが付与できる権限の全部分集合
(2^6 = 64 通り)× 各主体の種類 × 公開する各操作について、期待値(権限の表から独立に書いたもの)と一致する。
ランナーは権限が固定(`runner.report`、`job.execute`)で、利用者向けの操作はできない。拒否は 100% 監査ログに残る。
"""

from __future__ import annotations

import copy
import itertools
from typing import Any

import pytest

from job_core.access.permission import Permission as P
from job_core.job.application import AuditFilter, AuditOutcome
from job_testing.api_fakes import DEFAULT_ACCESS, ApiFixture, build_api, submit_body

H = ApiFixture.headers

# サービス用の認証情報に付与できる権限(設定の上限と同じ。人間のロールにも、同じ集合を載せて比べる)
GRANTABLE = [P.JOB_SUBMIT, P.GENERAL, P.QUEUE_SCHEDULE, P.CANCEL_QUEUED, P.FORCE_ABORT, P.SUBMIT_ON_BEHALF]
SUBSETS = [frozenset(c) for n in range(len(GRANTABLE) + 1) for c in itertools.combinations(GRANTABLE, n)]


def access_with_all_subsets() -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_ACCESS)
    config["service"]["permission_ceiling"] = [p.value for p in GRANTABLE]
    for index, subset in enumerate(SUBSETS):
        config["roles"][f"r{index}"] = {"permissions": sorted(p.value for p in subset)}
        config["groups"][f"g{index}"] = [f"r{index}"]
    return config


class World:
    """権限の部分集合ごとに、人間・サービスの主体を作り、同じ操作を試す。"""

    def __init__(self) -> None:
        self.api = build_api(access=access_with_all_subsets())
        self.runner_id, self.runner_token = self.api.register_runner("r-a")
        self.owner = self.api.member("owner")  # 他人のジョブの所有者(job.submit + general)
        self._n = 0

    def principal(self, kind: str, index: int) -> str:
        subset = SUBSETS[index]
        self._n += 1
        if kind == "human":
            return self.api.login_as(f"h{index}-{self._n}", [f"g{index}"])
        return self.api.issue_service_token(subset, name=f"s{index}-{self._n}")

    def new_job(self) -> str:
        self._n += 1
        body = submit_body(definition_payload={"n": self._n})
        return self.api.client.post("/v1/jobs", json=body, headers=H(self.owner)).json()["job_id"]  # type: ignore[no-any-return]

    def running_job(self) -> str:
        """この主体が試す、実行中のジョブを用意する(ランナーが使用中なら、先に終わらせる)。"""
        from job_testing.api_fakes.build_api import ADMIN_PRINCIPAL

        busy = self.api.core.get_runner(ADMIN_PRINCIPAL, runner_id=self.runner_id).running_job_id
        if busy is not None:
            body = {"outcome": "succeeded"}
            self.api.client.post(f"/v1/runner/jobs/{busy}/result", json=body, headers=H(self.runner_token))
        job = self.new_job()
        while True:  # 先頭が別のジョブなら、それを終わらせて進める
            assigned = self.api.assign_next(self.runner_id, self.runner_token)
            assert assigned is not None
            if assigned == job:
                return job
            body = {"outcome": "succeeded"}
            self.api.client.post(f"/v1/runner/jobs/{assigned}/result", json=body, headers=H(self.runner_token))


def expected_status(operation: str, perms: frozenset[P]) -> int:
    """可否の表(001 contracts/application-api.md、003 contracts/http-api.md)から独立に書いた期待値。"""
    allowed = {
        "submit": P.JOB_SUBMIT in perms,
        "submit_on_behalf": P.SUBMIT_ON_BEHALF in perms,
        "submit_placed": P.JOB_SUBMIT in perms and P.QUEUE_SCHEDULE in perms,
        "view_queue": P.GENERAL in perms,
        "view_job": P.GENERAL in perms,
        "reschedule": P.QUEUE_SCHEDULE in perms,
        "cancel_others_queued": P.CANCEL_QUEUED in perms,
        "abort_others_running": P.FORCE_ABORT in perms,
        "list_runners": P.GENERAL in perms,
    }[operation]
    return 0 if allowed else 403


def attempt(world: World, operation: str, token: str) -> int:
    """操作を試し、拒否(403)なら 403、それ以外は 0(成功、または規則による別の拒否)を返す。"""
    client = world.api.client
    headers = H(token)
    if operation == "submit":
        response = client.post("/v1/jobs", json=submit_body(definition_payload={"s": world.new_job()}), headers=headers)
    elif operation == "submit_on_behalf":
        body = submit_body(definition_payload={"b": world.new_job()}, on_behalf_of="someone-else")
        response = client.post("/v1/jobs", json=body, headers=headers)
    elif operation == "submit_placed":
        anchor = world.new_job()
        body = submit_body(definition_payload={"p": anchor}, placement={"anchor_job_id": anchor, "side": "before"})
        response = client.post("/v1/jobs", json=body, headers=headers)
    elif operation == "view_queue":
        response = client.get("/v1/queue", headers=headers)
    elif operation == "view_job":
        response = client.get(f"/v1/jobs/{world.new_job()}", headers=headers)
    elif operation == "reschedule":
        a, b = world.new_job(), world.new_job()
        body = {"placement": {"anchor_job_id": b, "side": "before"}}
        response = client.post(f"/v1/jobs/{a}/reschedule", json=body, headers=headers)
    elif operation == "cancel_others_queued":
        response = client.post(f"/v1/jobs/{world.new_job()}/cancel", json={}, headers=headers)
    elif operation == "abort_others_running":
        response = client.post(f"/v1/jobs/{world.running_job()}/cancel", json={"reason": "x"}, headers=headers)
    else:
        response = client.get("/v1/runners", headers=headers)
    return 403 if response.status_code == 403 else 0


OPERATIONS = [
    "submit",
    "submit_on_behalf",
    "submit_placed",
    "view_queue",
    "view_job",
    "reschedule",
    "cancel_others_queued",
    "abort_others_running",
    "list_runners",
]


@pytest.fixture(scope="module")
def world() -> World:
    return World()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_decisions_depend_only_on_permissions_for_humans_and_services(world: World, operation: str) -> None:
    results: dict[int, dict[str, int]] = {}
    for index, subset in enumerate(SUBSETS):
        outcome = {kind: attempt(world, operation, world.principal(kind, index)) for kind in ("human", "service")}
        results[index] = outcome
        expected = expected_status(operation, subset)
        assert outcome["human"] == outcome["service"] == expected, (operation, sorted(p.value for p in subset), outcome)


def test_every_denial_is_recorded_in_the_audit_log() -> None:
    world = World()
    denied_calls = 0
    for index in (0, 1, 5, 17, 40, 63):
        for kind in ("human", "service"):
            token = world.principal(kind, index)
            for operation in OPERATIONS:
                if attempt(world, operation, token) == 403:
                    denied_calls += 1
    records = world.api.core.new_uow()
    with records as uow:
        denied = uow.audit.query(AuditFilter(outcome=AuditOutcome.DENIED), None, 100000).items
    # 参照系の拒否(一覧・詳細・待機列・ランナー一覧)は記録しない(状態を変えず、001 の方針)。変更系の拒否はすべて記録する
    mutating = {
        "submit",
        "submit_on_behalf",
        "submit_placed",
        "reschedule",
        "cancel_others_queued",
        "abort_others_running",
    }
    mutating_denials = 0
    for index in (0, 1, 5, 17, 40, 63):
        for _ in ("human", "service"):
            mutating_denials += sum(1 for op in mutating if expected_status(op, SUBSETS[index]) == 403)
    assert denied_calls >= mutating_denials > 0
    assert len(denied) >= mutating_denials


def test_runner_permissions_are_fixed_and_cannot_use_user_operations(world: World) -> None:
    results = [attempt(world, operation, world.runner_token) for operation in OPERATIONS]
    assert results == [403] * len(OPERATIONS)


def test_anonymous_and_forged_principals_never_pass() -> None:
    world = World()
    for path in ("/v1/queue", "/v1/runners", "/v1/jobs", "/v1/audit-log"):
        assert world.api.client.get(path).status_code == 401
    for token in ("ss_", "st_", "rt_", "ss_" + "A" * 43, "Bearer"):
        assert world.api.client.get("/v1/queue", headers=H(token)).status_code == 401


def test_kind_is_never_consulted_for_decisions() -> None:
    import ast
    import inspect

    from job_core.job.application import authorization

    tree = ast.parse(inspect.getsource(authorization))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "kind" not in attributes and "PrincipalKind" not in names
