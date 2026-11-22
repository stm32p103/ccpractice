"""アプリの骨格(T021): /healthz、未認証は 401、許可外の接続元は 403、3 種の主体の認証が通る。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.testclient import TestClient

from job_core_api.http.authn import CurrentPrincipal
from job_core_api.settings import ApiSettings
from job_testing.api_fakes import ApiFixture, build_api


def with_probe(api: ApiFixture) -> ApiFixture:
    router = APIRouter()

    @router.get("/v1/_probe")
    def read(principal: CurrentPrincipal) -> dict[str, object]:
        return {"subject": principal.subject_id, "kind": principal.kind.value}

    api.app.include_router(router)
    return api


def test_healthz_is_open_and_reports_ok() -> None:
    api = build_api()
    response = api.client.get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_unauthenticated_request_is_rejected_as_problem() -> None:
    api = with_probe(build_api())
    response = api.client.get("/v1/_probe")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_source_outside_the_allow_list_is_403_even_for_healthz() -> None:
    api = build_api(settings=ApiSettings(allowed_networks=("203.0.113.0/24",)))
    assert api.client.get("/healthz").status_code == 403


def test_three_kinds_of_principals_authenticate() -> None:
    api = with_probe(build_api())
    _, runner = api.runner_token()
    cases = {
        api.member("alice"): "human",
        api.issue_service_token(["job.submit"]): "service",
        runner: "runner",
    }
    for token, kind in cases.items():
        response = api.client.get("/v1/_probe", headers=ApiFixture.headers(token))
        assert response.status_code == 200 and response.json()["kind"] == kind


def test_unknown_path_and_method_are_problems() -> None:
    api = build_api()
    not_found = api.client.get("/v1/nothing")
    assert not_found.status_code == 404 and not_found.json()["code"] == "not_found"
    wrong_method = api.client.post("/healthz")
    assert wrong_method.status_code == 405 and wrong_method.json()["code"] == "method_not_allowed"


def test_openapi_and_docs_are_not_publicly_exposed() -> None:
    api = build_api()
    for path in ("/docs", "/redoc"):
        assert api.client.get(path).status_code == 404


def test_unhandled_exception_is_500_internal_error_without_details() -> None:
    api = build_api()
    router = APIRouter()

    @router.get("/v1/_boom")
    def boom() -> None:
        raise RuntimeError("password=hunter2")

    api.app.include_router(router)
    client = TestClient(api.app, client=("127.0.0.1", 1), raise_server_exceptions=False)
    response = client.get("/v1/_boom")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error" and "hunter2" not in response.text
    assert response.headers["x-request-id"] == response.json()["request_id"]
