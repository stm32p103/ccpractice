"""偽のランナー一覧(contracts/ports.md「RunnerEligibility」の Fake)。

ランナーの識別子 → 能力(キーと値)の表を持ち、「要件 = 能力の部分集合」とする単純な照合で判定する
(002 の照合規則の代わり)。要件は {"キー": "値", ...} の形の JSON を想定する。
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from job_core.job.domain.values import RunnerRequirement
from job_core.shared.ids import RunnerId


class FakeRunnerEligibility:
    def __init__(self) -> None:
        self._runners: dict[RunnerId, dict[str, object]] = {}
        self._lock = threading.Lock()
        self.calls = 0

    def register(self, runner_id: str, capabilities: Mapping[str, object]) -> RunnerId:
        with self._lock:
            self._runners[RunnerId(runner_id)] = dict(capabilities)
        return RunnerId(runner_id)

    def unregister(self, runner_id: str) -> None:
        with self._lock:
            self._runners.pop(RunnerId(runner_id), None)

    def any_registered_runner_may_satisfy(self, requirement: RunnerRequirement) -> bool:
        with self._lock:
            self.calls += 1
            return any(_satisfies(caps, requirement) for caps in self._runners.values())

    def runner_satisfies(self, runner_id: RunnerId, requirement: RunnerRequirement) -> bool:
        with self._lock:
            self.calls += 1
            caps = self._runners.get(runner_id)
            return caps is not None and _satisfies(caps, requirement)


def _satisfies(capabilities: Mapping[str, object], requirement: RunnerRequirement) -> bool:
    wanted = requirement.value
    if not isinstance(wanted, dict):
        return False
    return all(key in capabilities and capabilities[key] == value for key, value in wanted.items())
