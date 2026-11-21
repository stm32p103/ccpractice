"""識別子の型(data-model.md の JobId、RunnerId、SubjectId)。

いずれも不透明な文字列で、空であってはならない。
"""

from __future__ import annotations

from typing import NewType

JobId = NewType("JobId", str)
RunnerId = NewType("RunnerId", str)
SubjectId = NewType("SubjectId", str)


def is_valid_id(value: object) -> bool:
    """識別子として受け付けられる値(空でない文字列)かを返す。"""
    return isinstance(value, str) and value.strip() != ""
