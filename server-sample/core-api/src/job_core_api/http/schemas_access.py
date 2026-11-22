"""アクセスの管理のモデル(contracts/http-api.md §2.5)。

認証情報の値は、発行の応答の型(IssuedServiceCredentialOut)だけに置く(FR-026、T-A1)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ..access.config import AccessConfig
from ..access.config_reload import ReloadResult
from ..access.credentials import IssuedServiceCredential, ServiceCredentialView
from .schemas_jobs import ApiModel


class IssueCredentialRequest(ApiModel):
    name: str = Field(description="1〜128 文字。有効な認証情報の間で一意")
    permissions: list[str] = Field(description="付与する権限。設定の「サービスに付与できる権限の上限」の部分集合")


class IssuedServiceCredentialOut(ApiModel):
    credential_id: str
    name: str
    subject_id: str
    permissions: list[str]
    created_at: datetime
    token: str = Field(description="認証情報の値。この応答だけで返り、以後は取得できない")

    @classmethod
    def of(cls, issued: IssuedServiceCredential) -> IssuedServiceCredentialOut:
        return cls(
            credential_id=issued.credential_id,
            name=issued.name,
            subject_id=issued.subject_id,
            permissions=sorted(p.value for p in issued.permissions),
            created_at=issued.created_at,
            token=issued.value,
        )


class ServiceCredentialOut(ApiModel):
    credential_id: str
    name: str
    subject_id: str
    permissions: list[str]
    created_at: datetime
    created_by: str
    revoked_at: datetime | None
    last_used_at: datetime | None

    @classmethod
    def of(cls, view: ServiceCredentialView) -> ServiceCredentialOut:
        return cls(
            credential_id=view.credential_id,
            name=view.name,
            subject_id=view.subject_id,
            permissions=sorted(p.value for p in view.permissions),
            created_at=view.created_at,
            created_by=view.created_by,
            revoked_at=view.revoked_at,
            last_used_at=view.last_used_at,
        )


class AccessMappingOut(ApiModel):
    roles: dict[str, list[str]] = Field(description="ロール名 → 権限")
    groups: dict[str, list[str]] = Field(description="所属グループ → ロール")
    default_roles: list[str]
    service_permission_ceiling: list[str]
    digest: str

    @classmethod
    def of(cls, config: AccessConfig) -> AccessMappingOut:
        return cls(
            roles={name: sorted(p.value for p in perms) for name, perms in sorted(config.roles.items())},
            groups={name: sorted(roles) for name, roles in sorted(config.group_roles.items())},
            default_roles=sorted(config.default_roles),
            service_permission_ceiling=sorted(p.value for p in config.service_permission_ceiling),
            digest=config.digest,
        )


class ReloadResultOut(ApiModel):
    digest_before: str
    digest_after: str
    changed: bool
    diff: dict[str, Any] = Field(description="ロール・グループの追加・削除・変更の要約")

    @classmethod
    def of(cls, result: ReloadResult) -> ReloadResultOut:
        return cls(
            digest_before=result.digest_before,
            digest_after=result.digest_after,
            changed=result.changed,
            diff=dict(result.diff),
        )
