"""ジョブ完了イベントの契約テスト(SC-010、FR-030。quickstart.md V8)。

- 直列化の結果が JSON Schema(contracts/job-completed-event.schema.json)に適合する
- パッケージ内のスキーマと、spec の契約のスキーマが一致する
- 任意の payload・結果の要約を持つジョブを終了させても、その値がイベントに現れない
"""

from __future__ import annotations

import json
from datetime import timedelta
from importlib import resources
from pathlib import Path

import jsonschema
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from job_core.job.application import JobState
from job_core.job.domain.events import JobCompleted
from job_testing.core_fakes import build_core

from ..acceptance.conftest import SUBMITTER_PERMS, principal

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_SCHEMA = REPO_ROOT / "specs" / "001-core-job-queue" / "contracts" / "job-completed-event.schema.json"


def packaged_schema() -> dict[str, object]:
    text = resources.files("job_core.job").joinpath("schemas/job_completed.v1.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


def test_packaged_schema_matches_spec_contract() -> None:
    assert packaged_schema() == json.loads(SPEC_SCHEMA.read_text(encoding="utf-8"))


def test_schema_forbids_additional_properties() -> None:
    schema = packaged_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])  # type: ignore[arg-type]


def test_event_fields_match_schema_properties() -> None:
    schema = packaged_schema()
    declared = {f for f in JobCompleted.__dataclass_fields__} | {"event_type", "schema_version"}
    assert declared == set(schema["properties"])  # type: ignore[arg-type]


json_leaf = st.one_of(st.none(), st.booleans(), st.integers(), st.text(min_size=8, max_size=40))
json_values = st.recursive(
    json_leaf,
    lambda children: st.one_of(
        st.lists(children, max_size=4), st.dictionaries(st.text(min_size=1, max_size=10), children, max_size=4)
    ),
    max_leaves=10,
)


def strings_in(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*strings_in(k), *strings_in(v))]
    if isinstance(value, list):
        return [s for item in value for s in strings_in(item)]
    return []


def _complete_and_serialize(payload: object, summary: str, outcome: JobState) -> tuple[dict[str, object], str]:
    core = build_core()
    core.runners.register("R1", {"os": "x"})
    alice = principal("alice", SUBMITTER_PERMS)
    runner = principal("runner", {"job.execute"})  # type: ignore[arg-type]
    job_id = core.submit(
        alice, job_type="t", requirement={"os": "x"}, payload=payload or {"k": 0}, timeout=timedelta(minutes=1)
    ).job_id
    core.assign(runner, runner_id="R1")
    core.report_finished(runner, runner_id="R1", job_id=job_id, outcome=outcome, result_summary=summary)

    with core.new_uow() as uow:
        entries = uow.outbox.fetch_pending(10)
    assert len(entries) == 1
    document = entries[0].event.to_dict()
    return document, json.dumps(document, ensure_ascii=False)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    payload=json_values,
    summary=st.text(min_size=8, max_size=200),
    outcome=st.sampled_from([JobState.SUCCEEDED, JobState.FAILED]),
)
def test_events_conform_to_schema_and_never_contain_payload_or_summary(
    payload: object, summary: str, outcome: JobState
) -> None:
    document, serialized = _complete_and_serialize(payload, summary, outcome)
    jsonschema.validate(document, packaged_schema(), format_checker=jsonschema.FormatChecker())
    # イベント自身の固定の項目(項目名・状態の値など)と偶然一致した文字列は、漏れとして数えない
    _, baseline = _complete_and_serialize({"k": 0}, "-", outcome)
    secrets = [s for s in [*strings_in(payload), summary] if len(s) >= 8 and s not in baseline]
    for secret in secrets:
        assert secret not in serialized
