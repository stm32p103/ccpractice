"""アクセス設定(対応表。data-model.md §2、research.md R6)。

所属グループ → ロール → 権限の対応。検証してから値を作り、不正なら AccessConfigInvalid を送出する。
違反の一覧は場所と理由だけを持ち、ファイルの内容の抜粋を含めない。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from job_core.access.permission import Permission

ROLE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MAX_GROUP_KEY_LENGTH = 256

# ロールに載せられない権限(ランナーの主体・定期処理の主体に固定の権限。R6)
NON_ROLE_PERMISSIONS: frozenset[Permission] = frozenset(
    {Permission.JOB_EXECUTE, Permission.RUNNER_REPORT, Permission.RETENTION_PURGE, Permission.RUNNER_SWEEP}
)
# サービス用の認証情報の上限に載せられない権限(管理系は載せない。T-A3)
NON_SERVICE_PERMISSIONS: frozenset[Permission] = NON_ROLE_PERMISSIONS | {
    Permission.RUNNER_MANAGE,
    Permission.ACCESS_MANAGE,
    Permission.AUDIT_READ_ALL,
}

DEFAULT_SERVICE_CEILING: frozenset[Permission] = frozenset(
    {Permission.JOB_SUBMIT, Permission.GENERAL, Permission.SUBMIT_ON_BEHALF, Permission.QUEUE_SCHEDULE}
)


@dataclass(frozen=True)
class Violation:
    location: str
    reason: str


class AccessConfigInvalid(Exception):
    """アクセス設定が検証に通らない。違反は場所と理由だけ(内容の抜粋を含めない)。"""

    def __init__(self, violations: Iterable[Violation]) -> None:
        self.violations: tuple[Violation, ...] = tuple(violations)
        super().__init__("アクセス設定が不正: " + "; ".join(f"{v.location}: {v.reason}" for v in self.violations))


@dataclass(frozen=True)
class AccessConfig:
    """対応表(AccessConfig.roles、.group_roles、.default_roles、.service_permission_ceiling、.digest)。"""

    roles: Mapping[str, frozenset[Permission]]
    group_roles: Mapping[str, frozenset[str]]
    default_roles: frozenset[str]
    service_permission_ceiling: frozenset[Permission]
    digest: str

    def permissions_of(self, groups: Iterable[str]) -> frozenset[Permission]:
        """所属グループから権限を導く。当たるロールがなければ default_roles を使う。"""
        matched: set[str] = set()
        for group in groups:
            matched |= self.group_roles.get(group, frozenset())
        role_names = matched if matched else set(self.default_roles)
        permissions: set[Permission] = set()
        for role in role_names:
            permissions |= self.roles.get(role, frozenset())
        return frozenset(permissions)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AccessConfig:
        """TOML を読んだ後の構造(contracts/access-config.schema.json)から作る。"""
        violations: list[Violation] = []
        roles = _parse_roles(data.get("roles"), violations)
        group_roles = _parse_groups(data.get("groups"), roles, violations)
        default_roles = _parse_default_roles(data.get("default_roles"), roles, violations)
        ceiling = _parse_ceiling(data.get("service"), violations)
        for key in data:
            if key not in {"roles", "groups", "default_roles", "service"}:
                violations.append(Violation(str(key)[:64], "未知の項目"))
        if violations:
            raise AccessConfigInvalid(violations)
        return cls(
            roles=roles,
            group_roles=group_roles,
            default_roles=default_roles,
            service_permission_ceiling=ceiling,
            digest=_digest(roles, group_roles, default_roles, ceiling),
        )


def _permission_set(
    value: Any, location: str, forbidden: frozenset[Permission], violations: list[Violation]
) -> frozenset[Permission]:
    if not isinstance(value, list):
        violations.append(Violation(location, "配列でなければならない"))
        return frozenset()
    result: set[Permission] = set()
    for item in value:
        try:
            permission = Permission(item)
        except ValueError:
            violations.append(Violation(location, "未知の権限"))
            continue
        if permission in forbidden:
            violations.append(Violation(location, f"載せられない権限: {permission.value}"))
            continue
        result.add(permission)
    return frozenset(result)


def _parse_roles(value: Any, violations: list[Violation]) -> dict[str, frozenset[Permission]]:
    roles: dict[str, frozenset[Permission]] = {}
    if not isinstance(value, Mapping):
        violations.append(Violation("roles", "表でなければならない"))
        return roles
    for name, body in value.items():
        location = f"roles.{str(name)[:32]}"
        if not isinstance(name, str) or not ROLE_NAME.match(name):
            violations.append(Violation(location, "ロール名の形式が不正"))
            continue
        if not isinstance(body, Mapping) or set(body) != {"permissions"}:
            violations.append(Violation(location, "permissions だけを持つ表でなければならない"))
            continue
        roles[name] = _permission_set(body["permissions"], f"{location}.permissions", NON_ROLE_PERMISSIONS, violations)
    return roles


def _role_refs(value: Any, location: str, roles: Mapping[str, Any], violations: list[Violation]) -> frozenset[str]:
    if not isinstance(value, list):
        violations.append(Violation(location, "配列でなければならない"))
        return frozenset()
    refs: set[str] = set()
    for item in value:
        if not isinstance(item, str) or item not in roles:
            violations.append(Violation(location, "未定義のロールの参照"))
            continue
        refs.add(item)
    return frozenset(refs)


def _parse_groups(value: Any, roles: Mapping[str, Any], violations: list[Violation]) -> dict[str, frozenset[str]]:
    groups: dict[str, frozenset[str]] = {}
    if not isinstance(value, Mapping):
        violations.append(Violation("groups", "表でなければならない"))
        return groups
    for index, (group, refs) in enumerate(value.items()):
        location = f"groups[{index}]"
        if not isinstance(group, str) or not 1 <= len(group) <= MAX_GROUP_KEY_LENGTH:
            violations.append(Violation(location, "所属グループの識別子は 1〜256 文字でなければならない"))
            continue
        groups[group] = _role_refs(refs, location, roles, violations)
    return groups


def _parse_default_roles(value: Any, roles: Mapping[str, Any], violations: list[Violation]) -> frozenset[str]:
    if value is None:
        violations.append(Violation("default_roles", "必須の項目がない"))
        return frozenset()
    return _role_refs(value, "default_roles", roles, violations)


def _parse_ceiling(value: Any, violations: list[Violation]) -> frozenset[Permission]:
    if not isinstance(value, Mapping) or set(value) != {"permission_ceiling"}:
        violations.append(Violation("service", "permission_ceiling だけを持つ表でなければならない"))
        return frozenset()
    return _permission_set(
        value["permission_ceiling"], "service.permission_ceiling", NON_SERVICE_PERMISSIONS, violations
    )


def _digest(
    roles: Mapping[str, frozenset[Permission]],
    group_roles: Mapping[str, frozenset[str]],
    default_roles: frozenset[str],
    ceiling: frozenset[Permission],
) -> str:
    """内容の正規化(キー・要素の並べ替え)に対する SHA-256。同じ内容なら同じ値になる。"""
    canonical = {
        "roles": {name: sorted(p.value for p in perms) for name, perms in sorted(roles.items())},
        "groups": {group: sorted(refs) for group, refs in sorted(group_roles.items())},
        "default_roles": sorted(default_roles),
        "service": sorted(p.value for p in ceiling),
    }
    text = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
