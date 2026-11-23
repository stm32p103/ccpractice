"""SourceFetcher の契約テスト(004 contracts/ports.md「SourceFetcher」)。

使い方: `fetcher`(SourceFetcher)と `seed(source, revision, files)`(取得元にファイルを用意する関数)と
`dest_folder`(WorkFolder)を定義して、このクラスを継承する。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

import pytest

from job_runner_agent.guard.workpath import WorkFolder
from job_runner_agent.source import SourceFetcher, SourceUnavailable
from job_runner_protocol.messages import SourceCredential

CREDENTIAL = SourceCredential("token", "contract-secret-value-0123", "2026-11-22T00:00:00Z")


class SourceFetcherContract:
    def test_fixed_revision_content_lands_in_dest(
        self,
        fetcher: SourceFetcher,
        seed: Callable[[str, str, Mapping[str, str]], None],
        dest_folder: WorkFolder,
    ) -> None:
        seed("repo-1", "rev-a", {"a.txt": "A", "dir/b.txt": "B"})
        seed("repo-1", "rev-b", {"a.txt": "OTHER"})
        asyncio.run(fetcher.fetch("repo-1", "rev-a", CREDENTIAL, dest_folder.path_of("src")))
        assert (dest_folder.root / "src" / "a.txt").read_text() == "A"
        assert (dest_folder.root / "src" / "dir" / "b.txt").read_text() == "B"

    def test_no_history_metadata_is_left(
        self,
        fetcher: SourceFetcher,
        seed: Callable[[str, str, Mapping[str, str]], None],
        dest_folder: WorkFolder,
    ) -> None:
        seed("repo-1", "rev-a", {"a.txt": "A", ".git/config": "META"})
        asyncio.run(fetcher.fetch("repo-1", "rev-a", CREDENTIAL, dest_folder.path_of("src")))
        assert not (dest_folder.root / "src" / ".git").exists()

    def test_unknown_revision_or_source_is_unavailable_without_leaking_credential(
        self,
        fetcher: SourceFetcher,
        seed: Callable[[str, str, Mapping[str, str]], None],
        dest_folder: WorkFolder,
    ) -> None:
        seed("repo-1", "rev-a", {"a.txt": "A"})
        for source, revision in (("repo-1", "no-such"), ("no-such-repo", "rev-a")):
            with pytest.raises(SourceUnavailable) as info:
                asyncio.run(fetcher.fetch(source, revision, CREDENTIAL, dest_folder.path_of("src")))
            assert CREDENTIAL.secret not in str(info.value) and CREDENTIAL.secret not in repr(info.value)

    def test_does_not_write_outside_dest(
        self,
        fetcher: SourceFetcher,
        seed: Callable[[str, str, Mapping[str, str]], None],
        dest_folder: WorkFolder,
    ) -> None:
        seed("repo-1", "rev-a", {"a.txt": "A"})
        before = {
            p for p in dest_folder.root.parent.rglob("*") if dest_folder.root not in p.parents and p != dest_folder.root
        }
        asyncio.run(fetcher.fetch("repo-1", "rev-a", CREDENTIAL, dest_folder.path_of("src")))
        after = {
            p for p in dest_folder.root.parent.rglob("*") if dest_folder.root not in p.parents and p != dest_folder.root
        }
        assert before == after

    def test_escaping_source_names_are_rejected(self, fetcher: SourceFetcher, dest_folder: WorkFolder) -> None:
        for source in ("..\\x", "C:\\x", "\\\\h\\s"):
            with pytest.raises(SourceUnavailable):
                asyncio.run(fetcher.fetch(source, "rev-a", CREDENTIAL, dest_folder.path_of("src")))
