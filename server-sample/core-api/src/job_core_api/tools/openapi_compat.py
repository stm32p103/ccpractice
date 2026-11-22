"""OpenAPI の破壊的変更の検査(research.md R3。SC-008)。

直前の公開版(`core-api/openapi/released/`)と現在の文書を比較し、既存のクライアントを壊す変更を検出する。
外部のコマンドに依存せず、OpenAPI を JSON として比較する。

壊す変更: パス・操作・応答の項目の削除、応答の状態コードの削除、要求の必須項目・必須の本文・必須のパラメーターの追加、
型・列挙の縮小(要求)、応答の項目の型の変更、認可の強化(`security` の追加・変更)。
許す変更: エンドポイント・任意の項目の追加、応答の項目の追加、応答の列挙値の追加(クライアントは未知の値を無視する)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

METHODS = ("get", "put", "post", "delete", "patch")
MAX_DEPTH = 12


class _Resolver:
    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document

    def resolve(self, schema: Any) -> Any:
        seen = 0
        while isinstance(schema, dict) and "$ref" in schema and seen < MAX_DEPTH:
            node: Any = self._document
            for part in schema["$ref"].removeprefix("#/").split("/"):
                node = node.get(part, {}) if isinstance(node, dict) else {}
            schema = node
            seen += 1
        return schema


def find_breaking_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """old(公開済み)から new への、既存のクライアントを壊す変更の一覧(空なら互換)。"""
    problems: list[str] = []
    old_r, new_r = _Resolver(old), _Resolver(new)
    for path, old_item in old.get("paths", {}).items():
        new_item = new.get("paths", {}).get(path)
        if new_item is None:
            problems.append(f"パスの削除: {path}")
            continue
        for method in METHODS:
            if method not in old_item:
                continue
            where = f"{method.upper()} {path}"
            if method not in new_item:
                problems.append(f"操作の削除: {where}")
                continue
            _compare_operation(where, old_item[method], new_item[method], old_r, new_r, problems)
    return problems


def _compare_operation(
    where: str, old: dict[str, Any], new: dict[str, Any], old_r: _Resolver, new_r: _Resolver, problems: list[str]
) -> None:
    # 認可の強化: 認証が要らなかった操作が要るようになる、または要求の方式が変わる
    old_security, new_security = old.get("security"), new.get("security")
    if old_security != new_security and (new_security or old_security):
        if not old_security and new_security:
            problems.append(f"認可の強化(認証が必要になった): {where}")
        elif old_security and new_security and _security_names(new_security) != _security_names(old_security):
            problems.append(f"認可の方式の変更: {where}")
    _compare_parameters(where, old, new, old_r, new_r, problems)
    _compare_request_body(where, old, new, old_r, new_r, problems)
    for status, old_response in old.get("responses", {}).items():
        new_response = new.get("responses", {}).get(status)
        if new_response is None:
            problems.append(f"応答の状態コードの削除: {where} {status}")
            continue
        old_content, new_content = old_response.get("content", {}), new_response.get("content", {})
        for media, old_media in old_content.items():
            if media not in new_content:
                problems.append(f"応答の媒体の削除: {where} {status} {media}")
                continue
            _compare_response_schema(
                f"{where} {status} {media}",
                old_media.get("schema", {}),
                new_content[media].get("schema", {}),
                old_r,
                new_r,
                problems,
                0,
            )


def _security_names(security: list[dict[str, Any]]) -> set[str]:
    return {name for requirement in security for name in requirement}


def _parameters(operation: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(p["in"], p["name"]): p for p in operation.get("parameters", [])}


def _compare_parameters(
    where: str, old: dict[str, Any], new: dict[str, Any], old_r: _Resolver, new_r: _Resolver, problems: list[str]
) -> None:
    old_params, new_params = _parameters(old), _parameters(new)
    for key, parameter in new_params.items():
        if key not in old_params:
            if parameter.get("required"):
                problems.append(f"必須のパラメーターの追加: {where} {key[1]}")
            continue
        if not old_params[key].get("required") and parameter.get("required"):
            problems.append(f"パラメーターが必須になった: {where} {key[1]}")
        _compare_request_schema(
            f"{where} パラメーター {key[1]}",
            old_params[key].get("schema", {}),
            parameter.get("schema", {}),
            old_r,
            new_r,
            problems,
            0,
        )


def _compare_request_body(
    where: str, old: dict[str, Any], new: dict[str, Any], old_r: _Resolver, new_r: _Resolver, problems: list[str]
) -> None:
    old_body, new_body = old.get("requestBody"), new.get("requestBody")
    if new_body is None:
        return
    if old_body is None:
        if new_body.get("required"):
            problems.append(f"必須の本文の追加: {where}")
        return
    if not old_body.get("required") and new_body.get("required"):
        problems.append(f"本文が必須になった: {where}")
    for media, old_media in old_body.get("content", {}).items():
        new_media = new_body.get("content", {}).get(media)
        if new_media is None:
            problems.append(f"受け付ける媒体の削除: {where} {media}")
            continue
        _compare_request_schema(
            f"{where} 本文 {media}", old_media.get("schema", {}), new_media.get("schema", {}), old_r, new_r, problems, 0
        )


def _types(schema: dict[str, Any]) -> set[str]:
    declared = schema.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return set(declared)
    return set()


def _variants(schema: dict[str, Any], resolver: _Resolver) -> list[dict[str, Any]]:
    schema = resolver.resolve(schema)
    options = schema.get("anyOf") or schema.get("oneOf")
    if options:
        return [resolver.resolve(option) for option in options]
    return [schema]


def _type_set(schema: dict[str, Any], resolver: _Resolver) -> set[str]:
    found: set[str] = set()
    for variant in _variants(schema, resolver):
        found |= _types(variant)
        if "enum" in variant and not _types(variant):
            found.add("enum")
    return found


def _compare_request_schema(
    where: str, old: Any, new: Any, old_r: _Resolver, new_r: _Resolver, problems: list[str], depth: int
) -> None:
    """要求: new は、old が受け付けたものをすべて受け付けなければならない。"""
    if depth > MAX_DEPTH or not isinstance(old, dict) or not isinstance(new, dict):
        return
    old_s, new_s = old_r.resolve(old), new_r.resolve(new)
    old_types, new_types = _type_set(old_s, old_r), _type_set(new_s, new_r)
    if old_types and new_types and not old_types <= new_types:
        problems.append(f"型の縮小(要求): {where} {sorted(old_types)} → {sorted(new_types)}")
        return
    old_enum, new_enum = old_s.get("enum"), new_s.get("enum")
    if old_enum is not None and new_enum is not None and not set(map(str, old_enum)) <= set(map(str, new_enum)):
        problems.append(f"列挙の縮小(要求): {where}")
    if old_enum is None and new_enum is not None:
        problems.append(f"列挙の追加による縮小(要求): {where}")
    old_props, new_props = old_s.get("properties", {}), new_s.get("properties", {})
    for name in set(new_s.get("required", [])) - set(old_s.get("required", [])):
        problems.append(f"必須の項目の追加(要求): {where}.{name}")
    for name, prop in old_props.items():
        if name in new_props:
            _compare_request_schema(f"{where}.{name}", prop, new_props[name], old_r, new_r, problems, depth + 1)
    if "items" in old_s and "items" in new_s:
        _compare_request_schema(f"{where}[]", old_s["items"], new_s["items"], old_r, new_r, problems, depth + 1)


def _compare_response_schema(
    where: str, old: Any, new: Any, old_r: _Resolver, new_r: _Resolver, problems: list[str], depth: int
) -> None:
    """応答: new は、old のクライアントが期待する項目を保たなければならない。"""
    if depth > MAX_DEPTH or not isinstance(old, dict) or not isinstance(new, dict):
        return
    old_s, new_s = old_r.resolve(old), new_r.resolve(new)
    old_types, new_types = _type_set(old_s, old_r), _type_set(new_s, new_r)
    if old_types and new_types and not new_types <= old_types:
        problems.append(f"型の変更(応答): {where} {sorted(old_types)} → {sorted(new_types)}")
        return
    old_props, new_props = old_s.get("properties", {}), new_s.get("properties", {})
    for name, prop in old_props.items():
        if name not in new_props:
            problems.append(f"応答の項目の削除: {where}.{name}")
            continue
        _compare_response_schema(f"{where}.{name}", prop, new_props[name], old_r, new_r, problems, depth + 1)
    for name in set(old_s.get("required", [])) - set(new_s.get("required", [])):
        if name in new_props:
            problems.append(f"応答の必須の項目が任意になった: {where}.{name}")
    if "items" in old_s and "items" in new_s:
        _compare_response_schema(f"{where}[]", old_s["items"], new_s["items"], old_r, new_r, problems, depth + 1)


def main(argv: list[str] | None = None) -> int:
    """`python -m job_core_api.tools.openapi_compat <公開版の JSON> <現在の JSON>`。互換なら 0、壊す変更があれば 1。"""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("使い方: openapi_compat <公開版の JSON> <現在の JSON>", file=sys.stderr)
        return 2
    old = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    new = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    problems = find_breaking_changes(old, new)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def check_against_released(current: dict[str, Any], released_dir: Path) -> list[str]:
    """公開版(released/ の JSON)と比較する。公開版がなければ何もしない(空)。"""
    problems: list[str] = []
    for released in sorted(released_dir.glob("*.json")):
        old = json.loads(released.read_text(encoding="utf-8"))
        problems += [f"{released.name}: {p}" for p in find_breaking_changes(old, current)]
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
