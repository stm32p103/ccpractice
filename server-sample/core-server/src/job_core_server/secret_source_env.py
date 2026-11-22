"""環境変数の SecretSource(開発・試験専用。contracts/ports.md「SecretSource」)。

本番の設定でこの実装を選ぶと、core-server は警告する(settings の検査)。値は、ログ・例外に出さない。
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from job_core_api.secret_source import SecretNotFound


class EnvSecretSource:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def get(self, name: str) -> str:
        value = self._environ.get(name)
        if value is None or value == "":
            raise SecretNotFound() from None
        return value

    def __repr__(self) -> str:
        return "EnvSecretSource()"
