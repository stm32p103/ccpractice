"""版と語彙の検査(research.md R3、R15。FR-019、FR-024)。"""

from __future__ import annotations

import json

from job_core_api.app import openapi_document
from job_core_api.http.versioning import API_PREFIX, MAJOR_VERSION
from job_core_api.settings import ApiSettings
from job_testing.api_fakes import ApiFixture, build_api
from job_testing.vocabulary import find_terms, forbidden_terms

H = ApiFixture.headers


def test_every_business_path_starts_with_v1_and_the_major_version_is_one() -> None:
    document = openapi_document()
    assert document["info"]["version"].split(".")[0] == str(MAJOR_VERSION) == "1"
    for path in document["paths"]:
        assert path == "/healthz" or path.startswith(API_PREFIX + "/"), path


def test_the_openapi_document_has_no_platform_or_domain_specific_terms() -> None:
    text = json.dumps(openapi_document(), ensure_ascii=False)
    assert find_terms(text, forbidden_terms()) == []


def test_deprecation_and_sunset_headers_can_be_enabled_for_a_deprecated_version() -> None:
    api = build_api(settings=ApiSettings(deprecation_sunset="Wed, 01 Jul 2099 00:00:00 GMT"))
    response = api.client.get("/v1/queue", headers=H(api.viewer()))
    assert response.headers["deprecation"] == "true"
    assert response.headers["sunset"] == "Wed, 01 Jul 2099 00:00:00 GMT"
    assert "deprecation" not in api.client.get("/healthz").headers  # 版つきでないパスには付けない


def test_current_version_has_no_deprecation_headers_by_default() -> None:
    api = build_api()
    response = api.client.get("/v1/queue", headers=H(api.viewer()))
    assert "deprecation" not in response.headers and "sunset" not in response.headers


def test_openapi_json_endpoint_requires_authentication_and_matches_the_generated_document() -> None:
    api = build_api()
    assert api.client.get("/openapi.json").status_code == 401
    served = api.client.get("/openapi.json", headers=H(api.viewer()))
    assert served.status_code == 200 and served.json() == json.loads(json.dumps(openapi_document()))
