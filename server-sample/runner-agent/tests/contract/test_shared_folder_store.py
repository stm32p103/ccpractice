"""SharedFolderArtifactStore が ArtifactStoreContract を通る(T040)と、共有フォルダ固有の検査。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from job_runner_agent.artifacts.port import ArtifactStore, ArtifactStoreError
from job_runner_agent.artifacts.shared_folder import SharedFolderArtifactStore
from job_runner_agent.settings import AgentSettings
from job_runner_protocol.messages import ArtifactReference
from job_testing.contracts.artifact_store import ArtifactStoreContract, make_file
from job_testing.runner_fakes.harness import base_settings


def settings_for(tmp_path: Path, **limits: int) -> AgentSettings:
    raw = base_settings(tmp_path)
    raw["artifact_store"] = {
        "kind": "shared_folder",
        "shared_folder": {"local_path": str(tmp_path / "results"), "unc_host": "runner-pc", "share_name": "results"},
        **limits,
    }
    return AgentSettings.from_mapping(raw)


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return SharedFolderArtifactStore(settings_for(tmp_path, store_quota_bytes=1_000_000).artifact_store)


@pytest.fixture
def read_stored(tmp_path: Path) -> Callable[[ArtifactReference], bytes]:
    def read(ref: ArtifactReference) -> bytes:
        assert ref.reference.startswith("\\\\runner-pc\\results\\")
        local = tmp_path / "results" / ref.reference.removeprefix("\\\\runner-pc\\results\\")
        return local.read_bytes()

    return read


@pytest.fixture
def age_job(tmp_path: Path) -> Callable[[str, int], None]:
    def age(job_id: str, days: int) -> None:
        folder = tmp_path / "results" / job_id
        old = folder.stat().st_mtime - days * 86400
        os.utime(folder, (old, old))

    return age


class TestSharedFolderStore(ArtifactStoreContract):
    pass


def test_reference_is_unc_with_configured_host_and_share(store: ArtifactStore, tmp_path: Path) -> None:
    ref = asyncio.run(store.put("job-9", "r.json", make_file(tmp_path, b"{}")))
    assert ref.reference == "\\\\runner-pc\\results\\job-9\\r.json" and ref.kind.value == "unc"


def test_quota_exhaustion_is_a_store_error_and_leaves_nothing(tmp_path: Path) -> None:
    store = SharedFolderArtifactStore(settings_for(tmp_path, store_quota_bytes=100).artifact_store)
    with pytest.raises(ArtifactStoreError):
        asyncio.run(store.put("job-1", "big.bin", make_file(tmp_path, b"x" * 500)))
    assert not list((tmp_path / "results").rglob("*.bin*"))


def test_job_id_cannot_escape_the_result_folder(store: ArtifactStore, tmp_path: Path) -> None:
    asyncio.run(store.put("..\\..\\evil", "a.txt", make_file(tmp_path, b"x")))
    written = [p for p in tmp_path.rglob("a.txt") if p.name == "a.txt" and "results" in p.parts]
    assert len(written) == 1 and (tmp_path / "results") in written[0].parents


def test_writes_only_inside_the_configured_folder(store: ArtifactStore, tmp_path: Path) -> None:
    asyncio.run(store.put("job-1", "a.txt", make_file(tmp_path, b"x")))
    outside = [p for p in tmp_path.rglob("*") if p.is_file() and "results" not in p.parts and p.name != "src.bin"]
    assert outside == []


def test_unwritable_folder_fails_the_self_check(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    raw = base_settings(tmp_path)
    raw["artifact_store"] = {
        "kind": "shared_folder",
        "shared_folder": {"local_path": str(blocker / "results"), "unc_host": "h", "share_name": "s"},
    }
    store = SharedFolderArtifactStore(AgentSettings.from_mapping(raw).artifact_store)
    with pytest.raises(ArtifactStoreError):
        asyncio.run(store.verify_writable())
