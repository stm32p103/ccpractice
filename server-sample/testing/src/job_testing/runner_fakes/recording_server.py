"""送信を記録する偽のサーバー(004 T022。SC-003)。

`RecordingTransport` は、CoreClient の送信先(偽のコアなど)の前に置いて、宛先(ホスト・パス)と本文を記録する。
`socket_watch()` は、エージェントのプロセスが開く外向きの接続(ループバック以外)を記録する。
台帳 E4〜E7 にない宛先・内容への通信が 0 件であることを検査するために使う。
"""

from __future__ import annotations

import contextlib
import json
import socket
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Sent:
    host: str
    method: str
    path: str
    body: Any


@dataclass
class RecordingTransport(httpx.AsyncBaseTransport):
    inner: httpx.AsyncBaseTransport
    sent: list[Sent] = field(default_factory=list)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body: Any = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = request.content.decode("utf-8", errors="replace")
        self.sent.append(Sent(request.url.host, request.method, request.url.path, body))
        return await self.inner.handle_async_request(request)

    @property
    def hosts(self) -> set[str]:
        return {item.host for item in self.sent}

    def text(self) -> str:
        return json.dumps([item.body for item in self.sent], ensure_ascii=False, default=str)


@contextlib.contextmanager
def socket_watch() -> Iterator[list[str]]:
    """with の間に開かれた、ループバック以外への接続の宛先を記録する。"""
    connections: list[str] = []
    original = socket.socket.connect

    def watched(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else str(address)
        if str(host) not in ("127.0.0.1", "::1", "localhost"):
            connections.append(str(host))
        return original(self, address)

    socket.socket.connect = watched  # type: ignore[method-assign,assignment]
    try:
        yield connections
    finally:
        socket.socket.connect = original  # type: ignore[method-assign]
