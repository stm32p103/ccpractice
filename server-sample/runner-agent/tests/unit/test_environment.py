"""環境ブロックの組み立て(T015。US2-2)。親の環境を継承しない。"""

from __future__ import annotations

import os
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from job_runner_agent.guard.environment import EnvRejected, build_environment

EXPECTED = {"SystemRoot", "TEMP", "TMP", "JOB_WORK_DIR", "JOB_SIGNAL_DIR"}


def build(**kw: Any) -> dict[str, str]:
    base: dict[str, Any] = {
        "env_allow": {"SystemRoot": "C:\\Windows"},
        "work_dir": "W",
        "tmp_dir": "T",
        "signal_dir": "S",
    }
    base.update(kw)
    return build_environment(**base)


def test_only_allowed_and_agent_variables() -> None:
    os.environ["PARENT_SECRET_DUMMY"] = "dummy-secret"
    try:
        env = build()
    finally:
        del os.environ["PARENT_SECRET_DUMMY"]
    assert set(env) == EXPECTED
    assert env["TEMP"] == "T" and env["JOB_SIGNAL_DIR"] == "S"


@given(
    st.dictionaries(
        st.from_regex(r"[A-Z][A-Z0-9_]{0,10}", fullmatch=True),
        st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), max_size=8),
        max_size=5,
    )
)
def test_parent_environment_never_leaks(parent: dict[str, str]) -> None:
    saved = dict(os.environ)
    try:
        os.environ.update(parent)
        env = build()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    assert set(env) == EXPECTED


def test_extra_env_requires_permission_for_the_name() -> None:
    assert build(allowed_names=["TOOL_MODE"], extra_env={"TOOL_MODE": "fast"})["TOOL_MODE"] == "fast"
    with pytest.raises(EnvRejected):
        build(extra_env={"TOOL_MODE": "fast"})
    with pytest.raises(EnvRejected):
        build(allowed_names=["TOOL_MODE"], extra_env={"OTHER": "x"})


@pytest.mark.parametrize("name", ["TEMP", "temp", "JOB_WORK_DIR", "SYSTEMROOT"])
def test_collisions_are_rejected(name: str) -> None:
    with pytest.raises(EnvRejected):
        build(allowed_names=[name], extra_env={name: "x"})


def test_value_limits_and_message_without_value() -> None:
    with pytest.raises(EnvRejected) as info:
        build(allowed_names=["X"], extra_env={"X": "SECRET" * 300})
    assert "SECRET" not in str(info.value)
    with pytest.raises(EnvRejected):
        build(allowed_names=["X"], extra_env={"X": "a\x00b"})


def test_env_allow_cannot_define_agent_names() -> None:
    with pytest.raises(EnvRejected):
        build(env_allow={"TEMP": "x"})
