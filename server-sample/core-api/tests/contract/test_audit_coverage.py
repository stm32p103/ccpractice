"""網羅の検査(FR-020 の抜けの検出)。

OpenAPI の POST・PUT・DELETE の全操作が、監査の期待の表(操作 → 記録される AuditOperation、または理由つきの除外)に
載っていること、さらに、全操作を実際に 1 度ずつ実行したとき、表のとおりの記録が残ることを確かめる。
"""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

from job_core.job.domain.audit import AuditOperation as Op
from job_core_api.access.config import AccessConfig
from job_testing.api_fakes import DEFAULT_ACCESS, ApiFixture, build_api, submit_body

H = ApiFixture.headers
STATE_CHANGING = {"post", "put", "delete", "patch"}

# 操作(operation_id)→ 記録される AuditOperation のいずれか(成功時)。
EXPECTED: dict[str, set[Op]] = {
    "submit_job": {Op.SUBMIT, Op.SUBMIT_PLACED},
    "retry_job": {Op.RETRY},
    "reschedule_job": {Op.RESCHEDULE},
    "cancel_job": {Op.CANCEL_QUEUED, Op.ABORT_REQUEST},
    "create_runner": {Op.RUNNER_CREATE},
    "set_runner_maintenance": {Op.RUNNER_MAINTENANCE_SET},
    "clear_runner_maintenance": {Op.RUNNER_MAINTENANCE_CLEAR},
    "clear_runner_fault": {Op.FAULT_CLEAR},
    "delete_runner": {Op.RUNNER_DELETE},
    "reissue_runner_token": {Op.TOKEN_ISSUE},
    "revoke_runner_token": {Op.TOKEN_REVOKE},
    "replace_capability_allowlist": {Op.ALLOWLIST_CHANGE},
    "runner_register": {Op.RUNNER_REGISTER},
    "runner_heartbeat": {Op.RUNNER_ONLINE},  # 状態が変わらない通知は記録しない(offline からの回復だけ)
    "runner_report_fault": {Op.FAULT_REPORT},
    "runner_report_recovered": {Op.FAULT_RECOVERED},
    "runner_request_job": {Op.ASSIGN},
    "runner_report_finished": {Op.COMPLETE},
    "runner_confirm_stopped": {Op.ABORT_CONFIRM},
    "issue_service_credential": {Op.SERVICE_CREDENTIAL_ISSUE},
    "revoke_service_credential": {Op.SERVICE_CREDENTIAL_REVOKE},
    "reload_access_config": {Op.ACCESS_CONFIG_CHANGE},
    "revoke_sessions_of": {Op.LOGOUT},
    "logout": {Op.LOGOUT},
    "login": {Op.LOGIN},
}
# 監査の対象外(理由つき)。状態を変える POST・PUT・DELETE は、原則として対象。
EXCLUDED: dict[str, str] = {}


def state_changing_operations() -> set[str]:
    spec = build_api().app.openapi()
    return {
        op["operationId"] for item in spec["paths"].values() for method, op in item.items() if method in STATE_CHANGING
    }


def test_every_state_changing_operation_has_an_audit_expectation() -> None:
    operations = state_changing_operations()
    missing = operations - set(EXPECTED) - set(EXCLUDED)
    assert missing == set(), f"監査の期待の表にない操作(監査の抜けの疑い): {sorted(missing)}"
    assert (set(EXPECTED) | set(EXCLUDED)) - operations == set(), "表にあるが API にない操作がある"
    assert all(reason.strip() for reason in EXCLUDED.values())


def test_a_full_scenario_leaves_the_expected_records_for_every_operation() -> None:
    api = build_api()
    admin, alice, op = api.admin("root"), api.member("alice"), api.operator("op")
    created = api.client.post("/v1/runners", json={"name": "r-a"}, headers=H(admin)).json()
    runner_id, token = created["runner_id"], created["token"]["token"]
    api.client.put("/v1/capability-allowlist", json={"entries": {"k1": "single"}}, headers=H(admin))
    api.client.post("/v1/runner/registration", json={"capabilities": {"k1": "v"}}, headers=H(token))
    j1 = api.client.post("/v1/jobs", json=submit_body(), headers=H(alice)).json()["job_id"]
    placed = submit_body(definition_payload={"n": 2}, placement={"anchor_job_id": j1, "side": "before"})
    j2 = api.client.post("/v1/jobs", json=placed, headers=H(op)).json()["job_id"]
    api.client.post(
        f"/v1/jobs/{j1}/reschedule", json={"placement": {"anchor_job_id": j2, "side": "before"}}, headers=H(op)
    )
    api.client.post(f"/v1/jobs/{j2}/cancel", json={}, headers=H(op))  # cancel_queued
    api.client.post(f"/v1/jobs/{j2}/retry", json={}, headers=H(op))
    api.client.post("/v1/runner/job-requests", headers=H(token))  # assign j1
    api.client.post(f"/v1/jobs/{j1}/cancel", json={"reason": "stop"}, headers=H(op))  # abort_request
    api.client.post(f"/v1/runner/jobs/{j1}/stopped", headers=H(token))  # abort_confirm
    assigned = api.client.post("/v1/runner/job-requests", headers=H(token)).json()["assignment"]["job_id"]
    api.client.post(f"/v1/runner/jobs/{assigned}/result", json={"outcome": "succeeded"}, headers=H(token))  # complete
    api.client.post("/v1/runner/fault", json={"description": "x"}, headers=H(token))
    api.client.delete("/v1/runner/fault", headers=H(token))
    api.client.post("/v1/runner/fault", json={"description": "y"}, headers=H(token))
    api.client.delete(f"/v1/runners/{runner_id}/fault", headers=H(admin))  # fault_clear
    api.client.put(f"/v1/runners/{runner_id}/maintenance", json={}, headers=H(admin))
    api.client.delete(f"/v1/runners/{runner_id}/maintenance", headers=H(admin))
    api.advance(timedelta(hours=1))  # offline にして、生存通知で online に戻す
    api.client.post("/v1/runner/heartbeat", headers=H(token))
    reissued = api.client.post(f"/v1/runners/{runner_id}/token", headers=H(admin)).json()["token"]
    api.client.delete(f"/v1/runners/{runner_id}/token", headers=H(admin))
    assert reissued
    api.client.delete(f"/v1/runners/{runner_id}", headers=H(admin))
    issued = api.client.post("/v1/service-credentials", json={"name": "s", "permissions": []}, headers=H(admin)).json()
    api.client.delete(f"/v1/service-credentials/{issued['credential_id']}", headers=H(admin))
    session = api.client.post("/v1/auth/login", json={"proof": {"subject": "u9"}, "delivery": "token"}).json()
    api.client.delete("/v1/auth/session", headers=H(session["session_token"]))
    api.client.delete("/v1/access/sessions", params={"subject_id": "u9"}, headers=H(admin))
    changed: dict[str, Any] = copy.deepcopy(DEFAULT_ACCESS)
    changed["default_roles"] = []
    api.access_source.replace(AccessConfig.from_mapping(changed))
    api.client.post("/v1/access/reload", headers=H(admin))

    log = api.client.get("/v1/audit-log", params={"limit": 200, "outcome": "succeeded"}, headers=H(admin)).json()
    recorded = {Op(r["operation"]) for r in log["items"]}
    unmet = {name: sorted(o.value for o in ops) for name, ops in EXPECTED.items() if not ops & recorded}
    assert unmet == {}, f"期待した監査の記録がない操作: {unmet}"
