"""ジョブ定義と提出者(data-model.md の JobDefinition、Submitter)。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from job_core.shared.ids import SubjectId, is_valid_id

from .errors import ValidationFailed
from .values import DuplicateKey, JobType, JsonValue, Payload, RunnerRequirement, SourceRef, Timeout


@dataclass(frozen=True)
class JobDefinition:
    """ジョブ定義(data-model.md JobDefinition.job_type、.requirement、.payload、.timeout、.source_ref)。

    やり直し(FR-018)では、この値をそのまま新しいジョブに渡す。
    """

    job_type: JobType
    requirement: RunnerRequirement
    payload: Payload
    timeout: Timeout
    source_ref: SourceRef | None = None

    def __post_init__(self) -> None:
        for name, expected in (
            ("job_type", JobType),
            ("requirement", RunnerRequirement),
            ("payload", Payload),
            ("timeout", Timeout),
        ):
            if not isinstance(getattr(self, name), expected):
                raise ValidationFailed(name, "必須")
        if self.source_ref is not None and not isinstance(self.source_ref, SourceRef):
            raise ValidationFailed("source_ref", "SourceRef でなければならない")

    @classmethod
    def create(
        cls,
        *,
        job_type: str | None,
        requirement: JsonValue,
        payload: JsonValue,
        timeout: timedelta | None,
        source: str | None = None,
        revision: str | None = None,
    ) -> JobDefinition:
        """生の値から作る。必須の欠落・制約の違反は ValidationFailed(FR-003)。"""
        if job_type is None:
            raise ValidationFailed("job_type", "必須")
        if timeout is None:
            raise ValidationFailed("timeout", "必須")
        if source is None and revision is not None:
            raise ValidationFailed("source_ref.source", "リビジョンだけを指定することはできない")
        return cls(
            job_type=JobType(job_type),
            requirement=RunnerRequirement.of(requirement),
            payload=Payload.of(payload),
            timeout=Timeout(timeout),
            source_ref=SourceRef(source, revision) if source is not None else None,
        )

    def duplicate_key(self) -> DuplicateKey | None:
        """出所情報があれば重複の判定の鍵を返す。なければ判定の対象外(FR-006)。"""
        if self.source_ref is None:
            return None
        return DuplicateKey(self.source_ref.source, self.source_ref.revision, self.job_type.value)


@dataclass(frozen=True)
class Submitter:
    """提出者(data-model.md Submitter.owner、Submitter.submitted_by)。

    owner は名義上の提出者で「自分のジョブ」の判定に使う。submitted_by は実際に提出した主体。
    """

    owner: SubjectId
    submitted_by: SubjectId

    def __post_init__(self) -> None:
        if not is_valid_id(self.owner):
            raise ValidationFailed("submitter.owner", "空でない識別子でなければならない")
        if not is_valid_id(self.submitted_by):
            raise ValidationFailed("submitter.submitted_by", "空でない識別子でなければならない")

    @property
    def is_on_behalf(self) -> bool:
        return self.owner != self.submitted_by
