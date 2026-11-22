"""PostgreSQL の試験の共有の部品(接続先の用意)。conftest から `pg_dsn` を取り込んで使う。

接続先は環境変数 `JOB_TEST_POSTGRES_DSN`(空のデータベース)。なければ、PATH(または標準の場所)の `initdb`・`pg_ctl` で、
ユーザー領域の一時インスタンスを作って使う(取得はしない。終了時に停止・撤去する)。どちらもなければ、試験を飛ばす。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


def find_postgres_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for root in sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin"), reverse=True) if os.name == "nt" else []:
        candidate = root / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    configured = os.environ.get("JOB_TEST_POSTGRES_DSN")
    if configured:
        yield configured
        return
    initdb, pg_ctl = find_postgres_tool("initdb"), find_postgres_tool("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.skip("PostgreSQL が使えない(JOB_TEST_POSTGRES_DSN も initdb もない)")
    base = Path(tempfile.mkdtemp(prefix="job-pg-"))
    data = base / "data"
    port = free_port()
    subprocess.run(
        [initdb, "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"],
        check=True,
        capture_output=True,
    )
    options = f"-p {port} -c listen_addresses=127.0.0.1 -c fsync=off -c synchronous_commit=off"
    subprocess.run(
        [pg_ctl, "-D", str(data), "-o", options, "-l", str(base / "log.txt"), "-w", "start"],
        check=True,
        stdout=subprocess.DEVNULL,  # 子のプロセスが出力のパイプを引き継ぐと、終了を待ち続けるため、パイプを使わない
        stderr=subprocess.DEVNULL,
    )
    try:
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        shutil.rmtree(base, ignore_errors=True)
