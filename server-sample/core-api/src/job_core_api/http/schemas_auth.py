"""認証・セッションのモデル(contracts/http-api.md §2.1)。

セッションの値(session_token)は、`delivery = token` のログインの応答だけに置く(T-A1)。
認証基盤の名称・概念を持ち込まない(FR-008)。proof は「文字列の対応表」として不透明に扱う。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from job_core.access.principal import PrincipalKind

from .schemas_jobs import ApiModel


class LoginRequest(ApiModel):
    proof: dict[str, str] = Field(description="本人性の証明。内容の意味は認証基盤の実装に依る(API は解釈しない)")
    delivery: Literal["cookie", "token"] = Field(
        default="cookie", description="セッションの値の返し方。cookie: Cookie に設定、token: 応答の本文に含める"
    )


class SessionInfo(ApiModel):
    principal_kind: PrincipalKind
    subject_id: str
    display_name: str | None
    permissions: list[str] = Field(
        description="現在の対応表で導いた権限。画面の表示の切り替え用(最終の認可は API が判定する)"
    )
    expires_at: datetime | None = Field(description="絶対期限。セッション以外の主体は null")
    idle_expires_at: datetime | None = Field(description="無操作による失効の日時。セッション以外の主体は null")
    session_token: str | None = Field(default=None, description="`delivery = token` のログインの応答だけ")
