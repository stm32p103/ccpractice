"""破壊的変更の検査(research.md R3)。壊す変更を検出し、互換を保つ追加は許す。"""

from __future__ import annotations

import copy
from typing import Any

from job_core_api.tools.openapi_compat import check_against_released, find_breaking_changes, main

BASE: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "t", "version": "1.0.0"},
    "paths": {
        "/v1/items": {
            "post": {
                "security": [{"bearerAuth": []}],
                "parameters": [{"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/NewItem"}}},
                },
                "responses": {
                    "201": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}},
                    },
                    "409": {"description": "conflict"},
                },
            },
            "get": {"responses": {"200": {"description": "ok"}}},
        },
        "/v1/other": {"get": {"responses": {"200": {"description": "ok"}}}},
    },
    "components": {
        "schemas": {
            "NewItem": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["a", "b"]},
                    "note": {"type": "string"},
                },
            },
            "Item": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}, "state": {"type": "string", "enum": ["x", "y"]}},
            },
        }
    },
}


def changed(mutate: Any) -> list[str]:
    new = copy.deepcopy(BASE)
    mutate(new)
    return find_breaking_changes(BASE, new)


def test_identical_documents_are_compatible() -> None:
    assert find_breaking_changes(BASE, copy.deepcopy(BASE)) == []


def test_removed_path_operation_response_and_response_field_are_breaking() -> None:
    assert any("パスの削除" in p for p in changed(lambda d: d["paths"].pop("/v1/other")))
    assert any("操作の削除" in p for p in changed(lambda d: d["paths"]["/v1/items"].pop("get")))
    assert any(
        "状態コードの削除" in p for p in changed(lambda d: d["paths"]["/v1/items"]["post"]["responses"].pop("409"))
    )
    assert any(
        "応答の項目の削除" in p for p in changed(lambda d: d["components"]["schemas"]["Item"]["properties"].pop("id"))
    )


def test_response_field_type_change_and_optional_required_are_breaking() -> None:
    assert any(
        "型の変更(応答)" in p
        for p in changed(lambda d: d["components"]["schemas"]["Item"]["properties"]["id"].update(type="integer"))
    )
    assert any("任意になった" in p for p in changed(lambda d: d["components"]["schemas"]["Item"].update(required=[])))


def test_new_required_request_field_parameter_and_body_are_breaking() -> None:
    assert any(
        "必須の項目の追加" in p
        for p in changed(lambda d: d["components"]["schemas"]["NewItem"].update(required=["name", "note"]))
    )
    assert any(
        "必須のパラメーターの追加" in p
        for p in changed(
            lambda d: d["paths"]["/v1/items"]["post"]["parameters"].append(
                {"name": "x", "in": "query", "required": True, "schema": {"type": "string"}}
            )
        )
    )
    assert any(
        "必須の本文の追加" in p
        for p in changed(lambda d: d["paths"]["/v1/other"]["get"].update(requestBody={"required": True, "content": {}}))
    )


def test_request_type_and_enum_narrowing_are_breaking() -> None:
    assert any(
        "型の縮小" in p
        for p in changed(lambda d: d["components"]["schemas"]["NewItem"]["properties"]["name"].update(type="integer"))
    )
    assert any(
        "列挙の縮小" in p
        for p in changed(lambda d: d["components"]["schemas"]["NewItem"]["properties"]["kind"].update(enum=["a"]))
    )


def test_authorization_strengthening_is_breaking() -> None:
    assert any(
        "認可の強化" in p
        for p in changed(lambda d: d["paths"]["/v1/other"]["get"].update(security=[{"bearerAuth": []}]))
    )
    assert any(
        "認可の方式の変更" in p
        for p in changed(lambda d: d["paths"]["/v1/items"]["post"].update(security=[{"cookieAuth": []}]))
    )


def test_compatible_additions_are_allowed() -> None:
    def add(d: dict[str, Any]) -> None:
        d["paths"]["/v1/new"] = {"get": {"responses": {"200": {"description": "ok"}}}}
        d["components"]["schemas"]["Item"]["properties"]["extra"] = {"type": "string"}
        d["components"]["schemas"]["Item"]["properties"]["state"]["enum"].append("z")  # 応答の列挙値の追加
        d["components"]["schemas"]["NewItem"]["properties"]["optional"] = {"type": "string"}
        d["components"]["schemas"]["NewItem"]["properties"]["kind"]["enum"].append("c")  # 要求の列挙の拡大
        d["paths"]["/v1/items"]["post"]["parameters"].append(
            {"name": "opt", "in": "query", "required": False, "schema": {"type": "string"}}
        )
        d["paths"]["/v1/items"]["post"]["responses"]["400"] = {"description": "bad"}

    assert changed(add) == []


def test_check_against_released_is_a_noop_without_released_documents(tmp_path: Any) -> None:
    assert check_against_released(BASE, tmp_path) == []


def test_check_against_released_reports_with_the_file_name(tmp_path: Any) -> None:
    import json

    (tmp_path / "openapi-v1.json").write_text(json.dumps(BASE), encoding="utf-8")
    broken = copy.deepcopy(BASE)
    broken["paths"].pop("/v1/other")
    problems = check_against_released(broken, tmp_path)
    assert problems and problems[0].startswith("openapi-v1.json: ")


def test_cli_exit_codes(tmp_path: Any) -> None:
    import json

    old, same, broken = tmp_path / "old.json", tmp_path / "same.json", tmp_path / "broken.json"
    old.write_text(json.dumps(BASE), encoding="utf-8")
    same.write_text(json.dumps(BASE), encoding="utf-8")
    bad = copy.deepcopy(BASE)
    bad["paths"].pop("/v1/other")
    broken.write_text(json.dumps(bad), encoding="utf-8")
    assert main([str(old), str(same)]) == 0
    assert main([str(old), str(broken)]) == 1
    assert main([]) == 2
