"""サービス用の認証情報のユースケース(research.md R4、R10。FR-009、FR-010、FR-026)。

発行・一覧・失効。権限は設定の上限の部分集合に限る(T-A3)。値は発行の応答だけで返し、以後どこにも現れない(T-A1)。
監査には、権限の一覧と識別子・名前だけを記録する(値・ハッシュは記録しない)。
操作者に `access.manage` がなければ拒否し、その拒否も記録する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from job_core.access.permission import Permission
from job_core.access.principal import Principal
from job_core.job.application.ports import CoreDependencies
from job_core.job.domain.audit import AuditOperation
from job_core.job.domain.errors import ConcurrencyConflict, PermissionDenied, ValidationFailed
from job_core.shared.ids import SubjectId

from .audit import append_success, make_audit_record, record_permission_denied
from .holder import AccessConfigHolder
from .models import InvalidModel, ServiceCredential
from .ports import ServiceCredentialRepository
from .secrets import TokenKind, hash_token, new_token

ACCESS_MANAGE = Permission.ACCESS_MANAGE
SERVICE_SUBJECT_PREFIX = "svc:"


class CredentialNotFoundError(Exception):
    def __init__(self, credential_id: str) -> None:
        super().__init__("認証情報が存在しない")
        self.credential_id = credential_id


@dataclass(frozen=True)
class IssuedServiceCredential:
    """発行の結果。value は発行のユースケースの戻り値にだけ現れる。repr に値を出さない。"""

    credential_id: str
    name: str
    subject_id: SubjectId
    permissions: frozenset[Permission]
    created_at: datetime
    value: str

    def __repr__(self) -> str:
        return f"IssuedServiceCredential(credential_id={self.credential_id!r}, name={self.name!r}, value=***)"

    __str__ = __repr__


@dataclass(frozen=True)
class ServiceCredentialView:
    """一覧・詳細の表示用。値・ハッシュを含まない。"""

    credential_id: str
    name: str
    subject_id: SubjectId
    permissions: frozenset[Permission]
    created_at: datetime
    created_by: SubjectId
    revoked_at: datetime | None
    last_used_at: datetime | None

    @classmethod
    def of(cls, credential: ServiceCredential) -> ServiceCredentialView:
        return cls(
            credential_id=credential.credential_id,
            name=credential.name,
            subject_id=credential.subject_id,
            permissions=credential.permissions,
            created_at=credential.created_at,
            created_by=credential.created_by,
            revoked_at=credential.revoked_at,
            last_used_at=credential.last_used_at,
        )


class ServiceCredentials:
    def __init__(
        self, deps: CoreDependencies, repository: ServiceCredentialRepository, access: AccessConfigHolder
    ) -> None:
        self._deps = deps
        self._repository = repository
        self._access = access

    def issue(self, principal: Principal, *, name: str, permissions: list[str]) -> IssuedServiceCredential:
        self._authorize(principal, AuditOperation.SERVICE_CREDENTIAL_ISSUE, {"name": name[:128]})
        granted = self._validated_permissions(permissions)
        credential_id = self._deps.ids.new_id()
        value = new_token(TokenKind.SERVICE)
        try:
            credential = ServiceCredential(
                credential_id=credential_id,
                name=name,
                subject_id=SubjectId(SERVICE_SUBJECT_PREFIX + credential_id),
                permissions=granted,
                token_hash=hash_token(value),
                created_at=self._deps.clock.now(),
                created_by=principal.subject_id,
            )
        except InvalidModel as exc:
            raise ValidationFailed("name", "1〜128 文字で、制御文字を含まない文字列でなければならない") from exc
        self._repository.add(credential)  # 同名の有効な認証情報があれば DuplicateCredentialName
        record = make_audit_record(
            self._deps,
            principal,
            AuditOperation.SERVICE_CREDENTIAL_ISSUE,
            after=_audit_fields(credential),
        )
        try:
            append_success(self._deps, record)
        except Exception:
            # 監査に残せなかった認証情報は使えないようにする(補償)
            self._revoke_quietly(credential)
            raise
        return IssuedServiceCredential(
            credential_id=credential.credential_id,
            name=credential.name,
            subject_id=credential.subject_id,
            permissions=credential.permissions,
            created_at=credential.created_at,
            value=value,
        )

    def list_all(self, principal: Principal) -> list[ServiceCredentialView]:
        self._authorize(principal, AuditOperation.SERVICE_CREDENTIAL_ISSUE, {"action": "list"})
        return [ServiceCredentialView.of(c) for c in self._repository.list()]

    def revoke(self, principal: Principal, *, credential_id: str) -> None:
        self._authorize(principal, AuditOperation.SERVICE_CREDENTIAL_REVOKE, {"credential_id": credential_id[:128]})
        for _ in range(self._deps.max_conflict_retries):
            credential = self._repository.get(credential_id)
            if credential is None:
                raise CredentialNotFoundError(credential_id)
            if credential.is_revoked:
                return  # 冪等(再度の失効では記録しない)
            try:
                self._repository.save(credential.revoke(self._deps.clock.now()))
            except ConcurrencyConflict:
                continue
            record = make_audit_record(
                self._deps, principal, AuditOperation.SERVICE_CREDENTIAL_REVOKE, after=_audit_fields(credential)
            )
            append_success(self._deps, record)
            return
        raise ConcurrencyConflict()

    def _authorize(self, principal: Principal, operation: AuditOperation, attempted: dict[str, Any]) -> None:
        if ACCESS_MANAGE not in principal.permissions:
            record_permission_denied(self._deps, principal, operation, (ACCESS_MANAGE.value,), attempted)
            raise PermissionDenied([ACCESS_MANAGE.value])

    def _validated_permissions(self, permissions: list[str]) -> frozenset[Permission]:
        ceiling = self._access.get().service_permission_ceiling
        granted: set[Permission] = set()
        for item in permissions:
            try:
                permission = Permission(item)
            except ValueError:
                raise ValidationFailed("permissions", "未知の権限は付与できない") from None
            if permission not in ceiling:
                raise ValidationFailed("permissions", "サービスに付与できる権限の上限の外にある")
            granted.add(permission)
        return frozenset(granted)

    def _revoke_quietly(self, credential: ServiceCredential) -> None:
        stored = self._repository.get(credential.credential_id)
        if stored is not None and not stored.is_revoked:
            self._repository.save(stored.revoke(self._deps.clock.now()))


def _audit_fields(credential: ServiceCredential) -> dict[str, Any]:
    return {
        "credential_id": credential.credential_id,
        "name": credential.name,
        "permissions": sorted(p.value for p in credential.permissions),
    }
