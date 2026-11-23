"""ログのマスク(research.md R10。補助的な対策であり、主たる防御ではない)。

(1) 完全一致: エージェントが保持する秘密の値と、その Base64・URL 符号化。(2) パターン: 既知の機密の形(既定 + 設定)。
置換は固定の `***`。複数行(PEM の秘密鍵)は開始から終了までを 1 つの `***` にする。
1 行が MAX_LINE を超えるときは、末尾の WINDOW 文字を残して先に出力する(境界をまたぐ一致は、一致の手前で切る)。
一致した内容は、戻り値・例外・属性のどこにも残さない(件数だけ)。
"""

from __future__ import annotations

import base64
import re
import urllib.parse
from collections.abc import Iterable

REPLACEMENT = "***"
MAX_LINE = 8192
WINDOW = 256
MIN_SECRET_LENGTH = 4

DEFAULT_PATTERNS: tuple[str, ...] = (
    r"\b(?:ss|st|rt)_[A-Za-z0-9_\-]{16,}",
    r"(?i:\bBearer)\s+[A-Za-z0-9._~+/=\-]{8,}",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}",
    r"(?i:\b(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)\S+",
)
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def _encodings(secret: str) -> set[str]:
    raw = secret.encode("utf-8")
    forms = {
        secret,
        base64.b64encode(raw).decode("ascii"),
        base64.urlsafe_b64encode(raw).decode("ascii"),
        base64.b64encode(raw).decode("ascii").rstrip("="),
        urllib.parse.quote(secret, safe=""),
        urllib.parse.quote_plus(secret),
    }
    return {f for f in forms if len(f) >= MIN_SECRET_LENGTH}


class StreamMasker:
    """1 本の出力ストリームのマスク。feed() で受け取った文字列から、確定した部分をマスクして返す。"""

    def __init__(self, secrets: Iterable[str] = (), patterns: Iterable[str] = ()) -> None:
        forms: set[str] = set()
        for secret in secrets:
            if len(secret) >= MIN_SECRET_LENGTH:
                forms |= _encodings(secret)
        parts = [re.escape(f) for f in sorted(forms, key=len, reverse=True)]
        self._exact = re.compile("|".join(parts)) if parts else None
        self._patterns = [re.compile(p) for p in (*DEFAULT_PATTERNS, *patterns)]
        self._pending = ""
        self._in_pem = False
        self.masked_lines = 0

    # ------------------------------------------------------------------ 公開

    def feed(self, text: str) -> str:
        """text を受け取り、行として確定した部分(と、長すぎる行の先頭)をマスクして返す。"""
        self._pending += text
        out: list[str] = []
        while True:
            newline = self._pending.find("\n")
            if newline < 0:
                break
            line, self._pending = self._pending[: newline + 1], self._pending[newline + 1 :]
            out.append(self._line(line))
        if len(self._pending) > MAX_LINE and not self._in_pem:
            cut = len(self._pending) - WINDOW
            for start, end in self._spans(self._pending):
                if start < cut < end:
                    cut = start
            head, self._pending = self._pending[:cut], self._pending[cut:]
            out.append(self._mask(head))
        return "".join(out)

    def flush(self) -> str:
        """未確定の末尾を、マスクして返す(出力の終了時)。"""
        rest, self._pending = self._pending, ""
        if not rest:
            return ""
        return self._line(rest)

    # ------------------------------------------------------------------ 内部

    def _line(self, line: str) -> str:
        if self._in_pem:
            if _PEM_END.search(line):
                self._in_pem = False
            return ""
        if _PEM_BEGIN.search(line):
            self.masked_lines += 1
            if not _PEM_END.search(line):
                self._in_pem = True
            return REPLACEMENT + ("\n" if line.endswith("\n") else "")
        return self._mask(line)

    def _spans(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        if self._exact is not None:
            spans += [m.span() for m in self._exact.finditer(text)]
        for pattern in self._patterns:
            spans += [m.span() for m in pattern.finditer(text)]
        return sorted(spans)

    def _mask(self, text: str) -> str:
        spans = self._spans(text)
        if not spans:
            return text
        merged: list[list[int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        pieces: list[str] = []
        cursor = 0
        for start, end in merged:
            pieces.append(text[cursor:start])
            pieces.append(REPLACEMENT)
            cursor = end
        pieces.append(text[cursor:])
        self.masked_lines += 1
        return "".join(pieces)


def mask_text(text: str, secrets: Iterable[str] = (), patterns: Iterable[str] = ()) -> tuple[str, int]:
    """1 つの短い文字列(summary など)をマスクして、(結果、マスクした行数)を返す。"""
    masker = StreamMasker(secrets, patterns)
    out = masker.feed(text) + masker.flush()
    return out, masker.masked_lines
