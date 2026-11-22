"""認証の依存関係: Bearer・Cookie、401、Origin の検査(research.md R5、T-A5)。"""

from __future__ import annotations

from fastapi import APIRouter

from job_core_api.http.authn import CurrentPrincipal
from job_testing.api_fakes import ApiFixture, build_api


def api_with_probe() -> ApiFixture:
    api = build_api()
    router = APIRouter()

    @router.get("/v1/_probe")
    def read(principal: CurrentPrincipal) -> dict[str, str]:
        return {"subject": principal.subject_id, "kind": principal.kind.value}

    @router.post("/v1/_probe")
    def write(principal: CurrentPrincipal) -> dict[str, str]:
        return {"subject": principal.subject_id}

    api.app.include_router(router)
    return api


def test_bearer_authenticates() -> None:
    api = api_with_probe()
    token = api.member("alice")
    response = api.client.get("/v1/_probe", headers=ApiFixture.headers(token))
    assert response.status_code == 200 and response.json() == {"subject": "alice", "kind": "human"}


def test_missing_or_bad_credentials_are_401_problem_with_www_authenticate() -> None:
    api = api_with_probe()
    for headers in ({}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer ss_x"}):
        response = api.client.get("/v1/_probe", headers=headers)
        assert response.status_code == 401, headers
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["code"] == "authentication_failed"


def test_cookie_authenticates_reads_without_origin() -> None:
    api = api_with_probe()
    token = api.member("alice")
    api.client.cookies.set(api.deps.settings.cookie_name, token)
    assert api.client.get("/v1/_probe").status_code == 200


def test_cookie_state_change_requires_matching_origin() -> None:
    api = api_with_probe()
    token = api.member("alice")
    api.client.cookies.set(api.deps.settings.cookie_name, token)
    no_origin = api.client.post("/v1/_probe")
    assert no_origin.status_code == 403 and no_origin.json()["code"] == "origin_not_allowed"
    foreign = api.client.post("/v1/_probe", headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    same = api.client.post("/v1/_probe", headers={"Origin": "http://testserver"})
    assert same.status_code == 200


def test_bearer_state_change_does_not_need_origin() -> None:
    api = api_with_probe()
    token = api.member("alice")
    assert api.client.post("/v1/_probe", headers=ApiFixture.headers(token)).status_code == 200


def test_configured_origin_list_replaces_same_origin_rule() -> None:
    from job_core_api.settings import ApiSettings

    api = build_api(settings=ApiSettings(allowed_origins=("https://ui.example",)))
    router = APIRouter()

    @router.post("/v1/_probe")
    def write(principal: CurrentPrincipal) -> dict[str, str]:
        return {"subject": principal.subject_id}

    api.app.include_router(router)
    api.client.cookies.set(api.deps.settings.cookie_name, api.member("alice"))
    assert api.client.post("/v1/_probe", headers={"Origin": "https://ui.example"}).status_code == 200
    assert api.client.post("/v1/_probe", headers={"Origin": "http://testserver"}).status_code == 403
