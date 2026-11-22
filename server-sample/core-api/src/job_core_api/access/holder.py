"""現在のアクセス設定(対応表)の保持。差し替えは検証済みの値だけ(research.md R6)。"""

from __future__ import annotations

import threading

from .config import AccessConfig


class AccessConfigHolder:
    def __init__(self, config: AccessConfig) -> None:
        self._config = config
        self._lock = threading.Lock()

    def get(self) -> AccessConfig:
        with self._lock:
            return self._config

    def replace(self, config: AccessConfig) -> AccessConfig:
        """差し替え、変更前の設定を返す。"""
        with self._lock:
            previous = self._config
            self._config = config
            return previous
