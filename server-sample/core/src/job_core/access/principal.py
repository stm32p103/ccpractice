"""主体(data-model.md の Principal.subject_id、Principal.permissions、Principal.kind)。

呼び出し元が認証済みの主体と権限の集合を渡す(FR-024)。core は認証しない。
kind は監査ログの表示(AuditRecord.actor_kind)にだけ使い、可否の判定には使わない。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from job_core.shared.ids import SubjectId, is_valid_id

from .permission import Permission


class PrincipalKind(StrEnum):
    HUMAN = "human"
    SERVICE = "service"
    SYSTEM = "system"
    RUNNER = "runner"


@dataclass(frozen=True)
class Principal:
    subject_id: SubjectId
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    kind: PrincipalKind = PrincipalKind.HUMAN

    def __post_init__(self) -> None:
        if not is_valid_id(self.subject_id):
            raise ValueError("Principal.subject_id は空でない文字列でなければならない")
        object.__setattr__(self, "permissions", frozenset(Permission(p) for p in self.permissions))
        object.__setattr__(self, "kind", PrincipalKind(self.kind))

    @classmethod
    def of(
        cls,
        subject_id: str,
        permissions: Iterable[Permission | str] = (),
        kind: PrincipalKind | str = PrincipalKind.HUMAN,
    ) -> Principal:
        return cls(SubjectId(subject_id), frozenset(Permission(p) for p in permissions), PrincipalKind(kind))

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions
