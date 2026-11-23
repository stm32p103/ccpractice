"""SourceCredentialIssuer の Fake(004 T072)。通信しない。呼び出しごとに新しい値を返す。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from job_core_api.runner_ports import SourceCredential, SourceNotAvailable


class FakeSourceCredentialIssuer:
    def __init__(self, now: Callable[[], datetime], *, lifetime: timedelta = timedelta(minutes=10)) -> None:
        self._now = now
        self._lifetime = lifetime
        self.issued: list[tuple[str, str, str | None]] = []
        self.available = True

    def issue(self, job_id: str, source: str, revision: str | None) -> SourceCredential:
        if not self.available:
            raise SourceNotAvailable
        self.issued.append((job_id, source, revision))
        return SourceCredential(
            "token", f"srcsecret-{len(self.issued):04d}-0123456789abcdef", self._now() + self._lifetime
        )
