"""ランナー向けのポート(004 contracts/ports.md「SourceCredentialIssuer」)。

core-api が外に求めるもの: ジョブのソースの取得資格の発行元。実アダプタ(取得先の認証。短命・読み取り専用)は 005
が実装し、
出力先を書き出し台帳に追加する。資格は保存せず、ログ・監査・エラー・イベントに値を含めない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class SourceNotAvailable(Exception):
    """取得資格の発行元がない構成、または発行できない。メッセージに値を含めない。"""


@dataclass(frozen=True)
class SourceCredential:
    """取得資格。secret は repr に出さない。kind は資格の種類を示す固定の語彙。"""

    kind: str
    secret: str = field(repr=False)
    expires_at: datetime


class SourceCredentialIssuer(Protocol):
    def issue(self, job_id: str, source: str, revision: str | None) -> SourceCredential:
        """指定の source・revision に限り、読み取り専用で短命の資格を発行する。呼び出しごとに新しい資格を返す。"""
        ...
