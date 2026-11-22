"""schemathesis による、実装が定義に適合することの検査(FR-003、SC-008。quickstart V20)。

Fake を配線したアプリに対し、認証つきで各エンドポイントの応答が定義に適合する(状態コード・媒体・本文の形)ことを
確かめる。
状態を変えるエンドポイントも、テスト用の状態(メモリ)で実行する。次は検査の対象から外す(理由つき):
- `/v1/events`: 終わらないストリーム(別に test_events で確かめる)
- `/v1/auth/session` の DELETE、`/v1/access/sessions`: 検査に使う認証情報そのものを失効させる
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.specs.openapi.checks import positive_data_acceptance

from job_core_api.app import openapi_document
from job_testing.api_fakes import ApiFixture, build_api, live_server, submit_body

# コアの意味の検証(要件の文法、識別子の形など)は、OpenAPI の型では表せない。定義に適合する要求でも
# 422 validation_failed などで拒否されうる(定義済みの応答)ため、「定義に適合する要求は受け付ける」検査は外す。
EXCLUDED_CHECKS = [positive_data_acceptance]

schema = schemathesis.openapi.from_dict(openapi_document())
schema = schema.exclude(path="/v1/events")
schema = schema.exclude(path="/v1/auth/session", method="DELETE")
schema = schema.exclude(path="/v1/access/sessions")


@pytest.fixture(scope="module")
def world() -> Iterator[tuple[ApiFixture, str]]:
    api = build_api()
    api.register_runner("r-seed")
    for n in range(3):  # 参照系のために、いくつかのジョブを用意する
        api.client.post(
            "/v1/jobs", json=submit_body(definition_payload={"n": n}), headers=ApiFixture.headers(api.member())
        )
    with live_server(api.app) as url:  # ループバックの実サーバー(接続元の許可リストを通る)
        yield api, url


@schema.exclude(path_regex=r"^/v1/runner/").parametrize()
@settings(max_examples=15, deadline=None, suppress_health_check=list(HealthCheck))
def test_user_facing_responses_conform_to_the_definition(
    case: schemathesis.Case, world: tuple[ApiFixture, str]
) -> None:
    api, url = world
    token = api.admin("schemathesis-admin")
    case.call_and_validate(base_url=url, headers={"Authorization": f"Bearer {token}"}, excluded_checks=EXCLUDED_CHECKS)


@schema.include(path_regex=r"^/v1/runner/").parametrize()
@settings(max_examples=15, deadline=None, suppress_health_check=list(HealthCheck))
def test_runner_facing_responses_conform_to_the_definition(
    case: schemathesis.Case, world: tuple[ApiFixture, str]
) -> None:
    api, url = world
    api._counter += 1
    _, token = api.register_runner(f"r-{api._counter}")
    case.call_and_validate(base_url=url, headers={"Authorization": f"Bearer {token}"}, excluded_checks=EXCLUDED_CHECKS)
