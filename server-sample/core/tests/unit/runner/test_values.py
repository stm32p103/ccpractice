"""runner の値オブジェクトの単体テスト(data-model.md §1)。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from job_core.job.domain.errors import ValidationFailed
from job_core.runner.domain.values import (
    Capabilities,
    FaultDescription,
    InvalidTimingPolicy,
    RunnerName,
    RunnerTimingPolicy,
    SetValue,
    SingleValue,
    TokenHash,
    parse_capability_key,
)


class TestRunnerName:
    def test_strips_and_accepts_bounds(self) -> None:
        assert RunnerName("  r-a  ").value == "r-a"
        assert RunnerName("a" * 128).value == "a" * 128

    @pytest.mark.parametrize("bad", ["", "   ", "a" * 129, "a\nb", "a\x00b"])
    def test_rejects(self, bad: str) -> None:
        with pytest.raises(ValidationFailed):
            RunnerName(bad)


class TestCapabilityKey:
    @pytest.mark.parametrize("good", ["k1", "a", "set.1", "a-b_c", "0x", "a" * 64])
    def test_accepts(self, good: str) -> None:
        assert parse_capability_key(good) == good

    @pytest.mark.parametrize("bad", ["", "K1", "-a", "_a", ".a", "a b", "a" * 65, "é", "a\n"])
    def test_rejects(self, bad: str) -> None:
        with pytest.raises(ValidationFailed):
            parse_capability_key(bad)


class TestCapabilityValue:
    def test_single_bounds(self) -> None:
        assert SingleValue("a").value == "a"
        assert SingleValue("a" * 256).value == "a" * 256
        for bad in ("", "a" * 257, "a\tb"):
            with pytest.raises(ValidationFailed):
                SingleValue(bad)

    def test_set_bounds_and_dedup(self) -> None:
        assert SetValue(frozenset()).values == frozenset()
        assert SetValue(frozenset(f"v{i}" for i in range(64))).kind.value == "set"
        with pytest.raises(ValidationFailed):
            SetValue(frozenset(f"v{i}" for i in range(65)))
        with pytest.raises(ValidationFailed):
            SetValue(frozenset({"ok", ""}))

    def test_capabilities_distinguish_single_and_set(self) -> None:
        single = Capabilities.of({"k1": "a"})
        as_set = Capabilities.of({"k1": ["a"]})
        assert single != as_set
        assert single.to_json() == {"k1": "a"}
        assert Capabilities.of({"set1": ["y", "x", "x"]}).to_json() == {"set1": ["x", "y"]}

    def test_capabilities_key_limit(self) -> None:
        Capabilities.of({f"k{i}": "v" for i in range(64)})
        with pytest.raises(ValidationFailed):
            Capabilities.of({f"k{i}": "v" for i in range(65)})

    def test_capabilities_reject_bad_type(self) -> None:
        with pytest.raises(ValidationFailed):
            Capabilities.of({"k1": 5})


class TestFaultDescription:
    def test_bounds(self) -> None:
        assert FaultDescription(" e1 ").value == "e1"
        assert len(FaultDescription("a" * 200).value) == 200

    @pytest.mark.parametrize("bad", ["", "  ", "a" * 201, "a\nb", "a\rb", "a\x1fb", "a\x7fb"])
    def test_rejects(self, bad: str) -> None:
        with pytest.raises(ValidationFailed):
            FaultDescription(bad)

    def test_error_does_not_echo_value(self) -> None:
        secret = "S3CRET-" + "x" * 300
        with pytest.raises(ValidationFailed) as err:
            FaultDescription(secret)
        assert "S3CRET" not in str(err.value)


class TestTokenHash:
    def test_requires_hex_64(self) -> None:
        TokenHash("a" * 64)
        for bad in ("", "a" * 63, "A" * 64, "g" * 64):
            with pytest.raises(ValidationFailed):
                TokenHash(bad)

    def test_does_not_show_value(self) -> None:
        h = TokenHash("ab" * 32)
        assert "ab" * 8 not in repr(h)
        assert "ab" * 8 not in str(h)


class TestRunnerTimingPolicy:
    def test_defaults(self) -> None:
        policy = RunnerTimingPolicy()
        assert policy.heartbeat_interval == timedelta(seconds=30)
        assert policy.offline_after == timedelta(seconds=90)
        assert policy.lease_duration == timedelta(seconds=180)

    def test_boundary_is_exactly_twice_the_interval(self) -> None:
        RunnerTimingPolicy(
            heartbeat_interval=timedelta(seconds=30),
            offline_after=timedelta(seconds=60),
            lease_duration=timedelta(seconds=60),
        )
        with pytest.raises(InvalidTimingPolicy):
            RunnerTimingPolicy(offline_after=timedelta(seconds=59))
        with pytest.raises(InvalidTimingPolicy):
            RunnerTimingPolicy(lease_duration=timedelta(seconds=59))

    def test_must_be_positive(self) -> None:
        with pytest.raises(InvalidTimingPolicy):
            RunnerTimingPolicy(heartbeat_interval=timedelta(0))
        with pytest.raises(InvalidTimingPolicy):
            RunnerTimingPolicy(heartbeat_interval=timedelta(seconds=-1))
