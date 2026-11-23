"""ランナープロトコルのスキーマと値オブジェクトの一致(T008)。"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from job_runner_protocol.messages import (
    ArtifactReference,
    Counters,
    FinishReport,
    HeartbeatResult,
    LogChunk,
    ProtocolViolation,
    SourceCredential,
)
from job_runner_protocol.validate import parse
from job_runner_protocol.vocabulary import ArtifactKind, FailureReason, Outcome, Stream

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "runner-protocol" / "schemas" / "runner-protocol.schema.json").read_text(encoding="utf-8"))
CONTRACT = ROOT / "specs" / "004-runner-agent" / "contracts" / "runner-protocol.schema.json"
SHA = "a" * 64


def validator(name: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]})


def test_schema_matches_contract() -> None:
    assert json.loads(CONTRACT.read_text(encoding="utf-8")) == SCHEMA


def test_failure_reason_vocabulary_matches_schema() -> None:
    assert {r.value for r in FailureReason} == set(SCHEMA["$defs"]["FailureReason"]["enum"])


def report() -> FinishReport:
    return FinishReport(
        Outcome.FAILED,
        "x",
        1,
        FailureReason.TOOL_FAILED,
        (ArtifactReference("a.txt", ArtifactKind.UNC, "\\\\host\\share\\job\\a.txt", 3, SHA),),
        Counters(1, 2, True),
    )


def test_roundtrip_conforms_to_schema() -> None:
    cases = {
        "FinishReport": report().to_json(),
        "LogChunk": LogChunk(0, Stream.STDOUT, "hello").to_json(),
        "HeartbeatResult": HeartbeatResult("online", None, 30.0, False).to_json(),
        "SourceCredential": SourceCredential("token", "s", "2026-11-22T00:00:00Z").to_json(),
    }
    for name, data in cases.items():
        validator(name).validate(data)
        parse(name, data)


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("LogChunk", {"seq": 0, "stream": "stdout", "text": "x", "extra": 1}),
        ("LogChunk", {"seq": -1, "stream": "stdout", "text": "x"}),
        ("LogChunk", {"seq": 0, "stream": "other", "text": "x"}),
        ("LogChunk", {"seq": 0, "stream": "stdout", "text": "x" * 65537}),
        ("FinishReport", {"outcome": "succeeded", "failure_reason": "timeout"}),
        ("FinishReport", {"outcome": "failed", "failure_reason": "unknown"}),
        ("FinishReport", {"outcome": "failed", "result_summary": "x" * 201}),
        ("FinishReport", {"outcome": "failed", "unknown": 1}),
    ],
)
def test_violations_are_rejected_by_both(name: str, data: dict[str, object]) -> None:
    assert list(validator(name).iter_errors(data))
    with pytest.raises(ProtocolViolation):
        parse(name, data)


def test_artifact_reference_forms() -> None:
    ArtifactReference("a.txt", ArtifactKind.URL, "https://store.example/a", 1, SHA)
    for kind, ref in [
        (ArtifactKind.UNC, "C:\\work\\a"),
        (ArtifactKind.URL, "http://x/a"),
        (ArtifactKind.UNC, "\\\\h\\s"),
    ]:
        with pytest.raises(ProtocolViolation):
            ArtifactReference("a.txt", kind, ref, 1, SHA)
        base = {"name": "a.txt", "kind": kind.value, "reference": ref, "size_bytes": 1, "sha256": SHA}
        assert list(validator("ArtifactReference").iter_errors(base))
    with pytest.raises(ProtocolViolation):
        ArtifactReference("a/b.txt", ArtifactKind.URL, "https://x/a", 1, SHA)


def test_violation_message_does_not_echo_input() -> None:
    with pytest.raises(ProtocolViolation) as info:
        parse("LogChunk", {"seq": 0, "stream": "stdout", "text": "x", "SECRET-KEY": "SECRET-VALUE"})
    assert "SECRET" not in str(info.value)


def test_credential_secret_not_in_repr() -> None:
    assert "topsecret" not in repr(SourceCredential("token", "topsecret", "t"))
