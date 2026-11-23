"""LocalDirectorySourceFetcher が SourceFetcherContract を通る(T072)。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from job_runner_agent.guard.workpath import WorkFolder
from job_runner_agent.source import LocalDirectorySourceFetcher, SourceFetcher
from job_testing.contracts.source_fetcher import SourceFetcherContract


@pytest.fixture
def fetcher(tmp_path: Path) -> SourceFetcher:
    return LocalDirectorySourceFetcher(tmp_path / "sources")


@pytest.fixture
def seed(tmp_path: Path) -> Callable[[str, str, Mapping[str, str]], None]:
    def put(source: str, revision: str, files: Mapping[str, str]) -> None:
        for name, text in files.items():
            path = tmp_path / "sources" / source / revision / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    return put


@pytest.fixture
def dest_folder(tmp_path: Path) -> WorkFolder:
    return WorkFolder.create(tmp_path / "work", "job-contract")


class TestLocalDirectorySourceFetcher(SourceFetcherContract):
    pass
