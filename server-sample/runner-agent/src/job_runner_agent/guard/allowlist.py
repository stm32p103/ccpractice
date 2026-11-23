"""許可リスト(S3: 既定は拒否)。リポジトリ・ツールの識別子。環境変数の名前の許可は environment.py と設定が担う。"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from ..settings import ToolSettings


class NotAllowed(LookupError):
    """許可リストにない。メッセージに入力の値を含めない。"""

    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


class RepositoryAllowlist:
    def __init__(self, allowed: Collection[str]) -> None:
        self._allowed = frozenset(allowed)

    def is_allowed(self, source: str | None) -> bool:
        return source is not None and source in self._allowed


class ToolRegistry:
    """tool_id → 実行ファイルの絶対パス。payload からパスを指定できない(R7)。"""

    def __init__(self, tools: Mapping[str, ToolSettings]) -> None:
        self._tools = dict(tools)

    def resolve(self, tool_id: str, permitted: Collection[str]) -> ToolSettings:
        if tool_id not in permitted or tool_id not in self._tools:
            raise NotAllowed("tool")
        return self._tools[tool_id]
