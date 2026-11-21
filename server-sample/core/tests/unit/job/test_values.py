"""値オブジェクトの境界値(data-model.md §1 の表のすべての行)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.job.domain.definition import JobDefinition, Submitter
from job_core.job.domain.errors import ValidationFailed
from job_core.job.domain.values import (
    DuplicateKey,
    JobType,
    Payload,
    Placement,
    PlacementSide,
    Reason,
    ResultSummary,
    RunnerRequirement,
    SourceRef,
    Timeout,
)
from job_core.shared.ids import JobId, SubjectId, is_valid_id


@pytest.mark.parametrize("value", ["a", "  a  ", "x" * 128, " " + "x" * 128 + " "])
def test_job_type_accepts_1_to_128_chars_after_strip(value: str) -> None:
    assert JobType(value).value == value.strip()


@pytest.mark.parametrize("value", ["", "   ", "x" * 129])
def test_job_type_rejects_out_of_range(value: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        JobType(value)
    assert error.value.field == "job_type"


def test_job_type_rejects_non_string() -> None:
    with pytest.raises(ValidationFailed):
        JobType(123)  # type: ignore[arg-type]


def test_payload_is_deep_copied_and_immutable() -> None:
    raw = {"a": [1, 2, {"b": "c"}]}
    payload = Payload.of(raw)
    raw["a"].append(99)  # type: ignore[attr-defined]
    assert payload.value == {"a": [1, 2, {"b": "c"}]}
    returned = payload.value
    returned["a"] = []
    assert payload.value == {"a": [1, 2, {"b": "c"}]}


@pytest.mark.parametrize("value", [{"k": 1}, [1, 2], "text", 0, False, 1.5])
def test_payload_accepts_any_json_value(value: object) -> None:
    assert Payload.of(value).value == value


def test_payload_and_requirement_are_required() -> None:
    with pytest.raises(ValidationFailed) as payload_error:
        Payload.of(None)
    assert payload_error.value.field == "payload"
    with pytest.raises(ValidationFailed) as requirement_error:
        RunnerRequirement.of(None)
    assert requirement_error.value.field == "requirement"


@pytest.mark.parametrize("value", [{1, 2}, object(), float("nan")])
def test_payload_rejects_non_json(value: object) -> None:
    with pytest.raises(ValidationFailed):
        Payload.of(value)


def test_payload_equality_ignores_key_order() -> None:
    assert Payload.of({"a": 1, "b": 2}) == Payload.of({"b": 2, "a": 1})


@pytest.mark.parametrize("value", [timedelta(seconds=1), timedelta(microseconds=1), timedelta(days=30)])
def test_timeout_accepts_positive(value: timedelta) -> None:
    assert Timeout(value).value == value


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_timeout_rejects_non_positive(value: timedelta) -> None:
    with pytest.raises(ValidationFailed) as error:
        Timeout(value)
    assert error.value.field == "timeout"


def test_source_ref_bounds() -> None:
    assert SourceRef("s" * 512, "r" * 256).revision == "r" * 256
    assert SourceRef("s").revision is None
    for source, revision in (("", None), ("s" * 513, None), ("s", ""), ("s", "r" * 257)):
        with pytest.raises(ValidationFailed):
            SourceRef(source, revision)


def test_result_summary_bounds() -> None:
    assert ResultSummary("").value == ""
    assert ResultSummary("x" * 1024).value == "x" * 1024
    with pytest.raises(ValidationFailed) as error:
        ResultSummary("x" * 1025)
    assert error.value.field == "result_summary"


def test_reason_bounds() -> None:
    assert Reason("  ok  ").value == "ok"
    assert Reason("x" * 1000).value == "x" * 1000
    for value in ("", "   ", "x" * 1001):
        with pytest.raises(ValidationFailed):
            Reason(value)


def test_placement() -> None:
    assert Placement.before("a") == Placement(JobId("a"), PlacementSide.BEFORE)
    assert Placement.after("a").side is PlacementSide.AFTER
    with pytest.raises(ValidationFailed):
        Placement(JobId(""), PlacementSide.BEFORE)
    with pytest.raises(ValidationFailed):
        Placement(JobId("a"), "middle")  # type: ignore[arg-type]


def test_ids() -> None:
    assert is_valid_id("x")
    assert not is_valid_id("")
    assert not is_valid_id("  ")
    assert not is_valid_id(None)


def _definition(**overrides: object) -> JobDefinition:
    values: dict[str, object] = {
        "job_type": "t",
        "requirement": {"os": "x"},
        "payload": {"k": 1},
        "timeout": timedelta(minutes=1),
    }
    values.update(overrides)
    return JobDefinition.create(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("missing", ["job_type", "requirement", "payload", "timeout"])
def test_job_definition_requires_fields(missing: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        _definition(**{missing: None})
    assert error.value.field == missing


def test_job_definition_rejects_revision_without_source() -> None:
    with pytest.raises(ValidationFailed):
        _definition(revision="r")


def test_duplicate_key() -> None:
    assert _definition().duplicate_key() is None
    assert _definition(source="s", revision="r").duplicate_key() == DuplicateKey("s", "r", "t")
    assert _definition(source="s").duplicate_key() == DuplicateKey("s", None, "t")


def test_submitter() -> None:
    own = Submitter(SubjectId("a"), SubjectId("a"))
    assert not own.is_on_behalf
    assert Submitter(SubjectId("a"), SubjectId("svc")).is_on_behalf
    with pytest.raises(ValidationFailed):
        Submitter(SubjectId(""), SubjectId("a"))
