"""SC-001・US1-5: 生成したクライアントだけで、提出から監査ログの参照までの一連の操作が成立する。

アプリの OpenAPI から openapi-python-client でクライアントを生成し、その公開の操作だけを呼ぶ
(API の URL・本文を手で組み立てない)。
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from job_testing.api_fakes import build_api
from job_testing.api_fakes.generated_client import PACKAGE, client_for, generate_client_package

# 001・002 の操作(契約 §2.2〜§2.4)に対応する operation_id。US1-5 の一覧検査。
REQUIRED_OPERATIONS = {
    "submit_job",
    "get_job",
    "get_job_history",
    "reschedule_job",
    "cancel_job",
    "retry_job",
    "create_runner",
    "list_runners",
    "get_runner",
    "get_runner_history",
    "set_runner_maintenance",
    "clear_runner_maintenance",
    "clear_runner_fault",
    "delete_runner",
    "reissue_runner_token",
    "revoke_runner_token",
    "get_capability_allowlist",
    "replace_capability_allowlist",
    "get_audit_log",
    "list_jobs",
    "get_queue",
    "runner_register",
    "runner_heartbeat",
    "runner_report_fault",
    "runner_report_recovered",
    "runner_request_job",
    "runner_report_finished",
    "runner_confirm_stopped",
}


@pytest.fixture(scope="module")
def package(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleType]:
    api = build_api()
    yield generate_client_package(api.app.openapi(), tmp_path_factory.mktemp("client"))


def operation(name: str, group: str) -> Any:
    return importlib.import_module(f"{PACKAGE}.api.{group}.{name}")


def model(name: str, module: str) -> Any:
    return getattr(importlib.import_module(f"{PACKAGE}.models.{module}"), name)


def test_us1_5_every_core_operation_has_an_openapi_operation() -> None:
    spec = build_api().app.openapi()
    operations = {op["operationId"] for item in spec["paths"].values() for op in item.values() if isinstance(op, dict)}
    assert operations >= REQUIRED_OPERATIONS


def test_sc_001_full_flow_with_the_generated_client_only(package: ModuleType) -> None:
    api = build_api()
    runner_id, runner_token = api.register_runner("r-a")  # 実行側の登録は 004 の範囲(ここではコアを直接呼ぶ)
    admin = client_for(package, api.client, api.admin("admin"))
    alice = client_for(package, api.client, api.member("alice"))
    operator = client_for(package, api.client, api.operator("op"))

    submit_job = operation("submit_job", "jobs")
    SubmitRequest, DefinitionIn, PlacementIn = (
        model("SubmitRequest", "submit_request"),
        model("DefinitionIn", "definition_in"),
        model("PlacementIn", "placement_in"),
    )
    PlacementInSide = model("PlacementInSide", "placement_in_side")

    def new_request(n: int, **kw: Any) -> Any:
        definition = DefinitionIn(
            requirement={"all": [{"key": "k1", "op": "eq", "value": "v"}]},
            payload={"n": n},
            timeout_seconds=60.0,
            job_type="t1",
        )
        return SubmitRequest(definition=definition, **kw)

    # 提出 → 参照
    first = submit_job.sync_detailed(client=alice, body=new_request(1))
    assert first.status_code == 201 and first.parsed.position == 1
    second = submit_job.sync_detailed(client=alice, body=new_request(2))
    third = submit_job.sync_detailed(client=alice, body=new_request(3))
    job1, job2, job3 = first.parsed.job_id, second.parsed.job_id, third.parsed.job_id
    detail = operation("get_job", "jobs").sync_detailed(job_id=job1, client=alice)
    assert detail.status_code == 200 and detail.parsed.summary.state.value == "queued"

    # スケジュール変更
    reschedule = operation("reschedule_job", "jobs").sync_detailed(
        job_id=job3,
        client=operator,
        body=model("RescheduleRequest", "reschedule_request")(
            placement=PlacementIn(anchor_job_id=job1, side=PlacementInSide.BEFORE)
        ),
    )
    assert reschedule.status_code == 200 and reschedule.parsed.position_after == 1

    # 取り消し(待機中)
    cancel_job = operation("cancel_job", "jobs")
    cancelled = cancel_job.sync_detailed(job_id=job2, client=alice, body=model("CancelRequest", "cancel_request")())
    assert cancelled.status_code == 200 and cancelled.parsed.abort_pending is False

    # 実行中のジョブの強制中断(理由が必須)→ やり直し
    assert any(r.runner_id == runner_id for r in operation("list_runners", "runners").sync(client=admin))
    assert api.assign_next(runner_id, runner_token) == job3
    no_reason = cancel_job.sync_detailed(job_id=job3, client=operator, body=model("CancelRequest", "cancel_request")())
    assert no_reason.status_code == 422 and no_reason.parsed.code == "reason_required"
    aborted = cancel_job.sync_detailed(
        job_id=job3, client=operator, body=model("CancelRequest", "cancel_request")(reason="stop")
    )
    assert aborted.status_code == 200 and aborted.parsed.abort_pending is True
    retried = operation("retry_job", "jobs").sync_detailed(
        job_id=job2, client=alice, body=model("RetryRequest", "retry_request")()
    )
    assert retried.status_code == 201 and retried.parsed.job_id not in {job1, job2, job3}

    # ランナーの管理
    created = operation("create_runner", "runners").sync_detailed(
        client=admin, body=model("CreateRunnerRequest", "create_runner_request")(name="r-new")
    )
    assert created.status_code == 201 and created.parsed.token.token.startswith("rt_")
    new_id = created.parsed.runner_id
    maintenance = operation("set_runner_maintenance", "runners").sync_detailed(
        runner_id=new_id, client=admin, body=model("MaintenanceRequest", "maintenance_request")()
    )
    assert maintenance.status_code == 200 and maintenance.parsed.state.value == "maintenance"
    assert (
        operation("clear_runner_maintenance", "runners").sync_detailed(runner_id=new_id, client=admin).status_code
        == 200
    )
    assert operation("revoke_runner_token", "runners").sync_detailed(runner_id=new_id, client=admin).status_code == 204
    assert operation("delete_runner", "runners").sync_detailed(runner_id=new_id, client=admin).status_code == 204

    # 監査ログの参照
    log = operation("get_audit_log", "audit").sync_detailed(client=admin)
    assert log.status_code == 200
    operations = {item.operation.value for item in log.parsed.items}
    assert {"submit", "reschedule", "cancel_queued", "abort_request", "retry", "runner_create"} <= operations


def test_error_responses_are_typed_problems(package: ModuleType) -> None:
    api = build_api()
    anonymous = client_for(package, api.client, "ss_unknown")
    response = operation("get_job", "jobs").sync_detailed(job_id="x", client=anonymous)
    assert response.status_code == 401 and response.parsed.code == "authentication_failed"


def test_generated_client_package_is_importable(package: ModuleType) -> None:
    assert Path(package.__file__ or "").exists()
