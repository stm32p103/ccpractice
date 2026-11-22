"""OpenAPI のスナップショットの検査(research.md R3。SC-008。quickstart V19)。

実装から生成した OpenAPI が `core-api/openapi/openapi-v1.json` と一致する。
意図しない変更があれば失敗し、更新の手順を示す。
直前の公開版(`core-api/openapi/released/`)があれば、破壊的変更がないことも確かめる。
"""

from __future__ import annotations

import json

import pytest

from job_core_api.app import openapi_document
from job_core_api.tools.export_openapi import RELEASED_DIR, SNAPSHOT, render
from job_core_api.tools.openapi_compat import check_against_released

UPDATE = (
    "更新するには: uv run python -m job_core_api.tools.export_openapi(意図した変更なら、更新したファイルをコミットする)"
)


def test_snapshot_matches_the_implementation() -> None:
    assert SNAPSHOT.exists(), f"スナップショットがない。{UPDATE}"
    expected = SNAPSHOT.read_text(encoding="utf-8")
    assert render(openapi_document()) == expected, f"OpenAPI の定義が、スナップショットと異なる。{UPDATE}"


def test_no_breaking_change_against_released_versions() -> None:
    problems = check_against_released(openapi_document(), RELEASED_DIR)
    assert problems == [], "公開版との破壊的変更: " + "; ".join(problems)


def test_snapshot_is_valid_json_with_a_stable_shape() -> None:
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert document["openapi"].startswith("3.")
    assert document["info"]["version"] == "1.0.0"
    assert all(path.startswith("/v1/") or path == "/healthz" for path in document["paths"])


@pytest.mark.parametrize("path", ["/v1/jobs", "/v1/runner/job-requests", "/v1/events", "/v1/auth/login"])
def test_expected_paths_are_present(path: str) -> None:
    assert path in json.loads(SNAPSHOT.read_text(encoding="utf-8"))["paths"]
