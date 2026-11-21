"""例外の基底。

すべての拒否は JobCoreError の派生で表し、機械可読の code と追加の情報(details)を持つ
(contracts/application-api.md「拒否の一覧」)。
"""

from __future__ import annotations

from typing import Any, ClassVar


class JobCoreError(Exception):
    """core が返す拒否の基底。"""

    code: ClassVar[str] = "job_core_error"

    def __init__(self, message: str = "", **details: Any) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details: dict[str, Any] = dict(details)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, details={self.details!r})"
