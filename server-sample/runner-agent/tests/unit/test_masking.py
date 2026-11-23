"""ログのマスク(T017。US2-5)。境界、PEM、Hypothesis。"""

from __future__ import annotations

import base64
import urllib.parse

from hypothesis import given
from hypothesis import strategies as st

from job_runner_agent.guard.masking import MAX_LINE, StreamMasker, mask_text

SECRET = "rt_abcdef0123456789ABCDEF"
SAFE = st.characters(blacklist_characters="\n", min_codepoint=32, max_codepoint=0x2FFF)


def run(chunks: list[str], secrets: list[str] | None = None) -> tuple[str, int]:
    masker = StreamMasker(secrets or [])
    out = "".join(masker.feed(c) for c in chunks) + masker.flush()
    return out, masker.masked_lines


def test_exact_secret_and_encodings_are_masked() -> None:
    secret = "s3cr3t-value-XYZ"
    for form in (
        secret,
        base64.b64encode(secret.encode()).decode(),
        urllib.parse.quote(secret, safe=""),
    ):
        out, lines = run([f"x {form} y\n"], [secret])
        assert form not in out and "***" in out and lines == 1


def test_default_patterns() -> None:
    cases = [
        "token rt_0123456789abcdef0123",
        "Authorization: Bearer abcdefgh12345678",
        "ghp_0123456789abcdefghijABCDEFGHIJ",
        "key AKIAABCDEFGHIJKLMNOP end",
        "jwt eyJhbGciOi.eyJzdWIiOiIx.SflKxwRJSMeKKF2QT4",
        "password=hunter2hunter2",
        "api_key: sk-live-123456",
    ]
    for line in cases:
        out, lines = run([line + "\n"])
        assert "***" in out and lines == 1, line
    assert "hunter2hunter2" not in run(["password=hunter2hunter2\n"])[0]


def test_non_secret_text_is_unchanged() -> None:
    text = "build ok\nwarning: something\n"
    assert run([text]) == (text, 0)


def test_secret_split_across_chunks_is_masked_when_line_completes() -> None:
    out, lines = run(["tok", "en=hun", "ter2hunter2\n"])
    assert "hunter2hunter2" not in out and lines == 1


def test_pem_block_is_replaced_as_a_whole() -> None:
    body = "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu"
    pem = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----\n"
    out, lines = run(["before\n", pem[:40], pem[40:], "after\n"])
    assert out == "before\n***\nafter\n" and lines == 1
    assert "MIIB" not in out


def test_long_line_secret_on_boundary_is_masked() -> None:
    secret = "LONGSECRET-0123456789-ABCDEFGH"
    for offset in range(0, 600, 37):
        line = "a" * (MAX_LINE - 256 - offset + 200) + secret + "b" * 3000
        out, _ = run([line[:5000], line[5000:], "\n"], [secret])
        assert secret not in out, offset
        assert len(out) >= len(line) - len(secret)


def test_masked_content_is_not_retained() -> None:
    masker = StreamMasker([SECRET])
    masker.feed(f"{SECRET}\n")
    assert SECRET not in str(masker.masked_lines)
    assert SECRET not in masker.feed("") and SECRET not in masker.flush()


def test_mask_text_helper() -> None:
    out, lines = mask_text(f"result {SECRET} done", [SECRET])
    assert out == "result *** done" and lines == 1


@given(prefix=st.text(alphabet=SAFE, max_size=60), suffix=st.text(alphabet=SAFE, max_size=60), cut=st.integers(0, 200))
def test_secret_never_appears_regardless_of_chunking(prefix: str, suffix: str, cut: int) -> None:
    secret = "Zq9!secret-token-VALUE"
    text = f"{prefix}{secret}{suffix}\n"
    cut = min(cut, len(text))
    out, _ = run([text[:cut], text[cut:]], [secret])
    assert secret not in out
