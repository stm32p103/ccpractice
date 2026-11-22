"""実際に待ち受けるサーバー(uvicorn をスレッドで起動)と SSE の読み取り(試験用)。

SSE は、TestClient では終わらない応答を扱えないため、ループバックの実サーバーで試験する。外部へは通信しない。
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI


@contextlib.contextmanager
def live_server(app: FastAPI) -> Iterator[str]:
    """アプリをループバックの空きポートで起動し、基底の URL を返す。"""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "サーバーが起動しなかった"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@dataclass
class SseMessage:
    event: str | None = None
    id: str | None = None
    data: str | None = None
    comment: str | None = None

    def json(self) -> dict[str, Any]:
        return json.loads(self.data or "{}")  # type: ignore[no-any-return]


@dataclass
class SseReader:
    """SSE を別スレッドで読み、メッセージを順に取り出せるようにする。"""

    base_url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] | None = None
    status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    body_on_error: str = ""
    messages: queue.Queue[SseMessage] = field(default_factory=queue.Queue)
    finished: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self._response: httpx.Response | None = None
        self._started = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._started.wait(10), "SSE の応答が始まらなかった"

    def _run(self) -> None:
        try:
            with (
                httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(15.0, read=15.0)) as client,
                client.stream("GET", "/v1/events", headers=self.headers, params=self.params) as response,
            ):
                self._response = response
                self.status = response.status_code
                self.response_headers = dict(response.headers)
                if response.status_code != 200:
                    self.body_on_error = response.read().decode("utf-8")
                    return
                self._started.set()
                current = SseMessage()
                for line in response.iter_lines():
                    if self._stop.is_set():
                        break
                    if line == "":
                        if current.event or current.data or current.comment:
                            self.messages.put(current)
                        current = SseMessage()
                    elif line.startswith(":"):
                        self.messages.put(SseMessage(comment=line[1:].strip()))
                    else:
                        name, _, value = line.partition(":")
                        value = value.removeprefix(" ")
                        if name == "event":
                            current.event = value
                        elif name == "id":
                            current.id = value
                        elif name == "data":
                            current.data = value
        except (httpx.HTTPError, OSError):
            pass
        finally:
            self._started.set()
            self.finished.set()

    def next(self, timeout: float = 5.0) -> SseMessage | None:
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty:
            return None

    def next_event(self, timeout: float = 5.0) -> SseMessage | None:
        """コメント(keepalive)を読み飛ばして、次のイベントを返す。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.next(max(0.0, deadline - time.monotonic()))
            if message is None:
                return None
            if message.event:
                return message
        return None

    def collect(self, count: int, timeout: float = 5.0) -> list[SseMessage]:
        found: list[SseMessage] = []
        deadline = time.monotonic() + timeout
        while len(found) < count and time.monotonic() < deadline:
            message = self.next_event(max(0.0, deadline - time.monotonic()))
            if message is None:
                break
            found.append(message)
        return found

    def close(self) -> None:
        self._stop.set()
        if self._response is not None:
            with contextlib.suppress(Exception):
                self._response.close()
