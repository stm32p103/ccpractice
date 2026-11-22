"""アクセス設定(対応表)の再読み込み(research.md R6。FR-007)。

読み込み → 検証 → 差し替え。検証に失敗したら現在の対応表を保つ。内容が変わったときは `ACCESS_CONFIG_CHANGE` を、
変更前後の digest と、ロール・グループの追加・削除・変更の差分で記録する(秘密情報は含まない)。
`access.manage` がなければ拒否し、その拒否も記録する。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from job_core.access.principal import Principal
from job_core.job.application.ports import CoreDependencies
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import PermissionDenied

from .audit import append_success, make_audit_record, record_permission_denied
from .config import AccessConfig
from .holder import AccessConfigHolder
from .ports import AccessConfigSource

ACCESS_MANAGE = "access.manage"


@dataclass(frozen=True)
class ReloadResult:
    digest_before: str
    digest_after: str
    changed: bool
    diff: Mapping[str, Any]


class AccessConfigReloader:
    def __init__(self, deps: CoreDependencies, source: AccessConfigSource, holder: AccessConfigHolder) -> None:
        self._deps = deps
        self._source = source
        self._holder = holder

    def current(self, principal: Principal) -> AccessConfig:
        self._authorize(principal, {"action": "read"})
        return self._holder.get()

    def reload(self, principal: Principal) -> ReloadResult:
        self._authorize(principal, {"action": "reload"})
        new = self._source.load()  # 不正なら AccessConfigInvalid(現在の対応表は変わらない)
        previous = self._holder.replace(new)
        diff = describe_diff(previous, new)
        changed = previous.digest != new.digest
        if changed:
            record = make_audit_record(
                self._deps,
                principal,
                AuditOperation.ACCESS_CONFIG_CHANGE,
                before={"digest": previous.digest},
                after={"digest": new.digest, "diff": diff},
            )
            append_success(self._deps, record)
        return ReloadResult(previous.digest, new.digest, changed, diff)

    def _authorize(self, principal: Principal, attempted: dict[str, Any]) -> None:
        if ACCESS_MANAGE not in {p.value for p in principal.permissions}:
            record_permission_denied(
                self._deps, principal, AuditOperation.ACCESS_CONFIG_CHANGE, (ACCESS_MANAGE,), attempted
            )
            raise PermissionDenied([ACCESS_MANAGE])


def _names(permissions: frozenset[Any]) -> list[str]:
    return sorted(getattr(p, "value", str(p)) for p in permissions)


def describe_diff(old: AccessConfig, new: AccessConfig) -> dict[str, Any]:
    """ロール・グループの追加・削除・変更の差分(名前と権限の一覧だけ)。"""
    roles_added = sorted(set(new.roles) - set(old.roles))
    roles_removed = sorted(set(old.roles) - set(new.roles))
    roles_changed = {
        name: {"before": _names(old.roles[name]), "after": _names(new.roles[name])}
        for name in sorted(set(old.roles) & set(new.roles))
        if old.roles[name] != new.roles[name]
    }
    groups_added = sorted(set(new.group_roles) - set(old.group_roles))
    groups_removed = sorted(set(old.group_roles) - set(new.group_roles))
    groups_changed = {
        name: {"before": sorted(old.group_roles[name]), "after": sorted(new.group_roles[name])}
        for name in sorted(set(old.group_roles) & set(new.group_roles))
        if old.group_roles[name] != new.group_roles[name]
    }
    diff: dict[str, Any] = {
        "roles": {"added": roles_added, "removed": roles_removed, "changed": roles_changed},
        "groups": {"added": groups_added, "removed": groups_removed, "changed": groups_changed},
    }
    if old.default_roles != new.default_roles:
        diff["default_roles"] = {"before": sorted(old.default_roles), "after": sorted(new.default_roles)}
    if old.service_permission_ceiling != new.service_permission_ceiling:
        diff["service_permission_ceiling"] = {
            "before": _names(old.service_permission_ceiling),
            "after": _names(new.service_permission_ceiling),
        }
    return diff
