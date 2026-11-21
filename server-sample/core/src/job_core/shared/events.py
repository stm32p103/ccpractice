"""ドメインイベントの基底。"""

from __future__ import annotations


class DomainEvent:
    """ドメインイベントの目印となる基底クラス。

    派生クラスは、一意の event_id と発生日時 occurred_at を持つ。
    """

    __slots__ = ()
