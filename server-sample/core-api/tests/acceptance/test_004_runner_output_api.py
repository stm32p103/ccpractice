"""004: ログ・成果物の参照、結果の報告の拡張、取得資格、リース切れの失敗の確定(API。T028、T046、T073、T049、T055)。"""

from __future__ import annotations

import json
from datetime import timedelta

from job_core.access.permission import Permission
from job_core.access.principal import Principal, PrincipalKind
from job_testing.api_fakes import ApiFixture, build_api, submit_body

H = ApiFixture.headers
SHA = "c" * 64
UNC = "\\\\runner-pc\\results\\job\\report.txt"


def running_job(api: ApiFixture, **definition: object) -> tuple[str, str, str]:
    runner_id, token = api.register_runner("r-a")
    body = submit_body()
    body["definition"].update(definition)
    job_id = api.client.post("/v1/jobs", json=body, headers=H(api.member("alice"))).json()["job_id"]
    assert api.assign_next(runner_id, token) == job_id
    return job_id, runner_id, token


def chunk(seq: int, text: str = "x", stream: str = "stdout") -> dict[str, object]:
    return {"seq": seq, "stream": stream, "text": text}


def test_logs_are_visible_only_with_read_output_and_reads_are_audited_without_content() -> None:
    api = build_api()
    job_id, _, token = running_job(api)
    for seq, text in enumerate(["SECRET-LOG-LINE-1\n", "line-2\n"]):
        assert (
            api.client.post(f"/v1/runner/jobs/{job_id}/logs", json=chunk(seq, text), headers=H(token)).status_code
            == 200
        )
    viewer, reader = api.viewer(), api.reader("rita")
    denied = api.client.get(f"/v1/jobs/{job_id}/logs", headers=H(viewer))
    assert denied.status_code == 403 and "job.read_output" in denied.json()["required_permissions"]
    page = api.client.get(f"/v1/jobs/{job_id}/logs", headers=H(reader))
    assert page.status_code == 200
    body = page.json()
    assert [c["text"] for c in body["chunks"]] == ["SECRET-LOG-LINE-1\n", "line-2\n"] and body["complete"] is False
    assert (
        api.client.get(f"/v1/jobs/{job_id}/logs?after_seq=0&limit=1", headers=H(reader)).json()["chunks"][0]["seq"] == 1
    )
    assert api.client.get(f"/v1/jobs/{job_id}/logs?limit=0", headers=H(reader)).status_code == 400
    audit = api.client.get("/v1/audit-log", headers=H(api.admin())).text
    assert "log_read" in audit and "rita" in audit and "SECRET-LOG-LINE-1" not in audit
    # ほかの閲覧・通知の経路にログの本文が現れない
    assert "SECRET-LOG-LINE-1" not in api.client.get(f"/v1/jobs/{job_id}", headers=H(reader)).text
    assert "SECRET-LOG-LINE-1" not in api.client.get("/v1/queue", headers=H(reader)).text


def test_log_append_is_limited_to_the_assigned_runner_and_runner_principals() -> None:
    api = build_api()
    job_id, _, token = running_job(api)
    other_id, other_token = api.register_runner("r-b")
    assert api.client.post(f"/v1/runner/jobs/{job_id}/logs", json=chunk(0), headers=H(other_token)).status_code == 403
    assert api.client.post(f"/v1/runner/jobs/{job_id}/logs", json=chunk(0), headers=H(api.admin())).status_code == 403
    assert api.client.post(f"/v1/runner/jobs/{job_id}/logs", json=chunk(0), headers=H(token)).status_code == 200
    assert (
        api.client.post(
            f"/v1/runner/jobs/{job_id}/logs", json={"seq": 0, "stream": "bad", "text": "x"}, headers=H(token)
        ).status_code
        == 400
    )
    too_big = {"seq": 1, "stream": "stdout", "text": "x" * 65537}
    assert api.client.post(f"/v1/runner/jobs/{job_id}/logs", json=too_big, headers=H(token)).status_code in (400, 413)
    assert other_id


def test_result_extension_artifacts_are_references_only_and_readable_with_permission() -> None:
    api = build_api()
    job_id, _, token = running_job(api)
    report = {
        "outcome": "failed",
        "result_summary": "要約",
        "exit_code": 2,
        "failure_reason": "tool_failed",
        "artifacts": [{"name": "report.txt", "kind": "unc", "reference": UNC, "size_bytes": 12, "sha256": SHA}],
        "counters": {"path_rejections": 1, "masked_lines": 2, "log_truncated": False},
    }
    finished = api.client.post(f"/v1/runner/jobs/{job_id}/result", json=report, headers=H(token))
    assert finished.status_code == 200 and finished.json()["state"] == "failed"
    reader = api.reader()
    listing = api.client.get(f"/v1/jobs/{job_id}/artifacts", headers=H(reader))
    assert listing.status_code == 200 and listing.json()["artifacts"][0]["reference"] == UNC
    assert api.client.get(f"/v1/jobs/{job_id}/artifacts", headers=H(api.viewer())).status_code == 403
    # 参照は、ジョブの詳細・一覧・待機列・監査ログ・通知に載らない
    for path in (f"/v1/jobs/{job_id}", "/v1/jobs", "/v1/queue"):
        assert "runner-pc" not in api.client.get(path, headers=H(reader)).text
    audit = api.client.get("/v1/audit-log", headers=H(api.admin())).text
    assert "runner-pc" not in audit and "tool_failed" in audit and "artifact_read" in audit
    assert "<unc>" not in audit


def test_invalid_result_extension_is_rejected_without_changing_the_job() -> None:
    api = build_api()
    job_id, _, token = running_job(api)
    bad_reports = [
        {"outcome": "failed", "failure_reason": "not-in-vocabulary"},
        {"outcome": "succeeded", "failure_reason": "tool_failed"},
        {"outcome": "failed", "result_summary": "x" * 201},
        {
            "outcome": "failed",
            "artifacts": [{"name": "a", "kind": "unc", "reference": "C:\\local\\a", "size_bytes": 1, "sha256": SHA}],
        },
        {
            "outcome": "failed",
            "artifacts": [{"name": "a", "kind": "url", "reference": "http://x/a", "size_bytes": 1, "sha256": SHA}],
        },
        {"outcome": "failed", "unknown_field": 1},
    ]
    for report in bad_reports:
        response = api.client.post(f"/v1/runner/jobs/{job_id}/result", json=report, headers=H(token))
        assert response.status_code in (400, 422), report
    assert api.client.get(f"/v1/jobs/{job_id}", headers=H(api.viewer())).json()["summary"]["state"] == "running"


def test_old_result_body_still_works() -> None:
    api = build_api()
    job_id, _, token = running_job(api)
    finished = api.client.post(
        f"/v1/runner/jobs/{job_id}/result", json={"outcome": "succeeded", "result_summary": "ok"}, headers=H(token)
    )
    assert finished.status_code == 200 and finished.json()["state"] == "succeeded"


def test_source_credential_is_issued_to_the_assigned_runner_only_and_never_recorded() -> None:
    api = build_api()
    job_id, _, token = running_job(api, source="repo-1", revision="abc123")
    other_id, other_token = api.register_runner("r-b")
    url = f"/v1/runner/jobs/{job_id}/source-credential"
    assert api.client.post(url, headers=H(other_token)).status_code == 403
    assert api.client.post(url, headers=H(api.admin())).status_code == 403
    first = api.client.post(url, headers=H(token))
    second = api.client.post(url, headers=H(token))
    assert first.status_code == 200 and first.json()["kind"] == "token" and first.json()["expires_at"]
    assert first.json()["secret"] != second.json()["secret"]
    assert api.source_issuer is not None and api.source_issuer.issued[0] == (job_id, "repo-1", "abc123")
    secret = first.json()["secret"]
    everything = (
        api.client.get("/v1/audit-log", headers=H(api.admin())).text
        + api.client.get(f"/v1/jobs/{job_id}", headers=H(api.viewer())).text
    )
    assert secret not in everything
    assert "secret" not in json.dumps(api.app.openapi()["paths"]["/v1/jobs"]).lower()
    api.client.post(f"/v1/runner/jobs/{job_id}/result", json={"outcome": "succeeded"}, headers=H(token))
    assert api.client.post(url, headers=H(token)).status_code == 409  # 実行中でない
    assert other_id


def test_source_credential_without_issuer_or_without_source_is_unavailable() -> None:
    api = build_api(with_source_issuer=False)
    job_id, _, token = running_job(api, source="repo-1")
    response = api.client.post(f"/v1/runner/jobs/{job_id}/source-credential", headers=H(token))
    assert response.status_code == 422 and response.json()["code"] == "source_not_available"
    api2 = build_api()
    job2, _, token2 = running_job(api2)  # source なし
    assert api2.client.post(f"/v1/runner/jobs/{job2}/source-credential", headers=H(token2)).status_code == 422


def test_lease_expiry_fails_the_job_and_the_late_report_is_rejected() -> None:
    api = build_api()
    job_id, _, token = running_job(api)
    api.advance(timedelta(seconds=200))
    sweeper = Principal.of("sweeper", [Permission.RUNNER_SWEEP], PrincipalKind.SYSTEM)
    api.core.sweep_runners(sweeper)
    summary = api.client.get(f"/v1/jobs/{job_id}", headers=H(api.viewer())).json()["summary"]
    assert summary["state"] == "failed"
    late = api.client.post(f"/v1/runner/jobs/{job_id}/result", json={"outcome": "succeeded"}, headers=H(token))
    assert late.status_code == 409
    assert api.client.get("/v1/queue", headers=H(api.viewer())).json()["items"] == []  # 待機列へ戻らない
