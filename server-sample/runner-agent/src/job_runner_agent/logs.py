"""ログの送信(research.md R10。FR-004)。

外部ツールの標準出力・標準エラーを、ストリームごとにデコード → マスク → チャンク化(1 秒または 64 KiB)→ seq
を付けて送る。
量の制限(総量・毎秒)を超えた分は破棄し、切り詰めの 1 行を 1 回だけ加える。ツールをブロックしない(読み取りは続ける)。
コアへ到達できない間は、マスク後のチャンクを溜めて、復旧後に seq の順に送る(再送は seq で冪等)。
"""

from __future__ import annotations

import asyncio
import codecs
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from job_runner_protocol.messages import LogChunk
from job_runner_protocol.vocabulary import MAX_LOG_CHUNK_CHARS, Stream

from .core_client import CoreClient, CoreRejected, CoreUnavailable
from .guard.masking import StreamMasker
from .retry import backoff_delays
from .settings import LogSettings

TRUNCATION_LINE = "[出力を切り詰めました]\n"


@dataclass(frozen=True)
class LogSummary:
    masked_lines: int
    truncated: bool
    chunks_sent: int


class LogSender:
    def __init__(
        self,
        client: CoreClient,
        job_id: str,
        settings: LogSettings,
        *,
        secrets: Iterable[str] = (),
        backlog_limit_chars: int = 64 * 1024 * 1024,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._job_id = job_id
        self._settings = settings
        self._sleep = sleep
        self._clock = clock
        self._backlog_limit = backlog_limit_chars
        secret_list = list(secrets)
        self._maskers = {s: StreamMasker(secret_list, settings.mask_patterns) for s in Stream}
        self._decoders = {s: codecs.getincrementaldecoder("utf-8")(errors="replace") for s in Stream}
        self._buffers: dict[Stream, list[str]] = {s: [] for s in Stream}
        self._buffer_chars = 0
        self._seq = 0
        self._emitted_chars = 0
        self._window_start = clock()
        self._window_chars = 0
        self._truncated = False
        self._truncation_marked = False
        self._queue: deque[LogChunk] = deque()
        self._queued_chars = 0
        self._wake = asyncio.Event()
        self._closing = False
        self._abandon = False
        self._quota_exhausted = False
        self._sent = 0
        self._sender: asyncio.Task[None] | None = None
        self._flusher: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ 公開

    def start(self) -> None:
        self._sender = asyncio.create_task(self._send_loop())
        self._flusher = asyncio.create_task(self._flush_loop())

    def feed(self, stream: Stream, data: bytes) -> None:
        """ツールの出力のバイト列を受け取る。ブロックしない。"""
        text = self._decoders[stream].decode(data)
        if not text:
            return
        self._accept(stream, self._maskers[stream].feed(text))

    async def finish(self) -> LogSummary:
        """出力の終了。残りをマスクして送り切る(abandon() されたら、送り切らずに戻る)。"""
        for stream in Stream:
            tail = self._decoders[stream].decode(b"", final=True)
            masker = self._maskers[stream]
            out = (masker.feed(tail) if tail else "") + masker.flush()
            self._accept(stream, out)
        if self._truncated and not self._truncation_marked:
            self._truncation_marked = True
            self._buffers[Stream.STDERR].append(TRUNCATION_LINE)
            self._buffer_chars += len(TRUNCATION_LINE)
        self._flush()
        self._closing = True
        self._wake.set()
        if self._flusher is not None:
            self._flusher.cancel()
        if self._sender is not None:
            await asyncio.gather(self._sender, return_exceptions=True)
        masked = sum(m.masked_lines for m in self._maskers.values())
        return LogSummary(masked, self._truncated, self._sent)

    def abandon(self) -> None:
        """送り切らずに終わる(エージェントの停止の信号など)。"""
        self._abandon = True
        self._wake.set()

    @property
    def truncated(self) -> bool:
        return self._truncated

    @property
    def masked_lines(self) -> int:
        return sum(m.masked_lines for m in self._maskers.values())

    # ------------------------------------------------------------------ 受け取りと制限

    def _accept(self, stream: Stream, text: str) -> None:
        if not text:
            return
        now = self._clock()
        if now - self._window_start >= 1.0:
            self._window_start, self._window_chars = now, 0
        allowed = text
        over_job = self._emitted_chars + len(text) > self._settings.max_bytes_per_job
        over_rate = self._window_chars + len(text) > self._settings.max_bytes_per_second
        if over_job or over_rate or self._quota_exhausted:
            self._truncated = True
            keep = max(
                0,
                min(
                    self._settings.max_bytes_per_job - self._emitted_chars,
                    self._settings.max_bytes_per_second - self._window_chars,
                ),
            )
            allowed = "" if self._quota_exhausted else text[:keep]
        if not allowed:
            return
        self._emitted_chars += len(allowed)
        self._window_chars += len(allowed)
        self._buffers[stream].append(allowed)
        self._buffer_chars += len(allowed)
        if self._buffer_chars >= MAX_LOG_CHUNK_CHARS:
            self._flush()

    def _flush(self) -> None:
        for stream in Stream:
            text = "".join(self._buffers[stream])
            self._buffers[stream] = []
            for offset in range(0, len(text), MAX_LOG_CHUNK_CHARS):
                piece = text[offset : offset + MAX_LOG_CHUNK_CHARS]
                if self._queued_chars + len(piece) > self._backlog_limit:
                    self._truncated = True  # 溜めすぎ(到達しない時間が長い)。新しい方を切り詰める
                    continue
                self._queue.append(LogChunk(self._seq, stream, piece))
                self._seq += 1
                self._queued_chars += len(piece)
        self._buffer_chars = 0
        if self._queue:
            self._wake.set()

    async def _flush_loop(self) -> None:
        interval = self._settings.flush_interval_ms / 1000
        while True:
            await self._sleep(interval)
            self._flush()

    # ------------------------------------------------------------------ 送信

    async def _send_loop(self) -> None:
        while True:
            if self._abandon:
                return
            if not self._queue:
                if self._closing:
                    return
                self._wake.clear()
                if not self._queue and not self._closing:
                    await self._wake.wait()
                continue
            chunk = self._queue[0]
            if await self._send(chunk):
                self._queue.popleft()
                self._queued_chars -= len(chunk.text)

    async def _send(self, chunk: LogChunk) -> bool:
        """チャンク 1 件を送る。送れた(または確定の拒否で破棄する)なら真。abandon なら偽。"""
        delays = backoff_delays()
        while not self._abandon:
            if self._quota_exhausted:
                return True
            try:
                await self._client.append_log(self._job_id, chunk)
            except CoreUnavailable:
                await self._sleep(next(delays))
                continue
            except CoreRejected as rejection:
                if rejection.code == "log_quota_exceeded":
                    self._truncated = True
                    self._quota_exhausted = True
                elif not rejection.final and rejection.status in (401,):
                    await self._sleep(next(delays))
                    continue
                return True  # 確定の拒否は破棄して続ける
            self._sent += 1
            return True
        return False
