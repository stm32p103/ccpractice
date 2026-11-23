"""US6: 許可リスト外のリポジトリを実行せず、ソースを取得資格つきで取得する(V22、V23、V26。FR-010、FR-026)。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from job_runner_agent.source import LocalDirectorySourceFetcher
from job_runner_protocol.messages import SourceCredential
from job_testing.runner_fakes.executors import payload
from job_testing.runner_fakes.harness import AgentHarness

ALLOW = {"source": {"repository_allowlist": ["sample-repo"], "fetcher": "remote"}}


def make_sources(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    revision = root / "sample-repo" / "abc123"
    (revision / ".git").mkdir(parents=True)
    (revision / ".git" / "config").write_text("GIT-METADATA")
    (revision / "src").mkdir()
    (revision / "src" / "f.txt").write_text("SOURCE-CONTENT", encoding="utf-8")
    (revision / "top.txt").write_text("top", encoding="utf-8")
    return root


class RecordingFetcher:
    """資格を受け取ったことを記録して、本物の取得に委ねる(資格が取得の後に残らないことの検査用)。"""

    def __init__(self, inner: LocalDirectorySourceFetcher) -> None:
        self.inner = inner
        self.received: list[str] = []

    async def fetch(self, source, revision, credential: SourceCredential | None, dest) -> None:  # type: ignore[no-untyped-def]
        assert credential is not None
        self.received.append(credential.secret)
        await self.inner.fetch(source, revision, credential, dest)


def test_us6_1_repository_outside_allowlist_is_rejected_before_any_work(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path, settings_overrides=ALLOW)
        job_id = h.core.enqueue("type-a", payload("echo", "SHOULD-NOT-RUN"), source="other-repo", revision="abc")
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "repository_not_allowed"
        assert h.core.log_text(job_id) == "" and h.core.credentials_issued == 0
        assert not Path(h.settings.work.root).exists() or h.work_root_entries() == []  # 作業フォルダを作らない
        assert any(r["event"] == "repository_rejected" and r["job_id"] == job_id for r in h.journal.read_audit())

    asyncio.run(scenario())


def test_v26_empty_allowlist_runs_no_job_that_needs_source_but_runs_jobs_without_source(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)  # 許可リストは空
        needs_source = h.core.enqueue("type-a", payload("echo", "x"), source="sample-repo", revision="abc")
        no_source = h.core.enqueue("type-a", payload("echo", "fine"))
        h.start()
        await h.wait_for(
            lambda: h.core.jobs[needs_source].state == "failed" and h.core.jobs[no_source].state == "succeeded"
        )
        await h.shutdown()
        report = h.core.jobs[needs_source].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "repository_not_allowed"

    asyncio.run(scenario())


def test_v23_credential_is_used_for_fetch_only_and_never_leaks(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = make_sources(tmp_path)
        fetcher = RecordingFetcher(LocalDirectorySourceFetcher(root))
        h = AgentHarness.create(tmp_path, settings_overrides=ALLOW, fetcher=fetcher)
        read_source = {"work": "src\\src\\f.txt"}
        listing = h.core.enqueue("type-a", payload("ls", {"work": "src"}), source="sample-repo", revision="abc123")
        content = h.core.enqueue("type-a", payload("cat", read_source), source="sample-repo", revision="abc123")
        env_job = h.core.enqueue("type-a", payload("env"), source="sample-repo", revision="abc123")
        h.start()
        await h.wait_for(lambda: all(h.core.jobs[j].state == "succeeded" for j in (listing, content, env_job)))
        await h.shutdown()
        assert h.core.log_text(content).strip() == "SOURCE-CONTENT"
        files = json.loads(h.core.log_text(listing))
        assert "top.txt" in files and not any(".git" in f for f in files)  # 履歴のメタデータを残さない
        assert h.core.credentials_issued == 3 and len(set(fetcher.received)) == 3  # 呼び出しごとに新しい資格
        everything = h.core.log_text(listing) + h.core.log_text(content) + h.core.log_text(env_job)
        state_text = "".join(
            p.read_text(errors="replace") for p in Path(h.settings.state.dir).rglob("*") if p.is_file()
        )
        for secret in fetcher.received:
            assert secret not in h.core.log_text(env_job)  # ツールの環境に渡らない
            assert secret not in state_text  # 状態フォルダ(ジャーナル・監査)に残らない
            assert secret not in everything and secret not in h.core.recorded_text()
        assert h.work_root_entries() == []

    asyncio.run(scenario())


def test_credential_value_in_tool_output_is_masked(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = make_sources(tmp_path)
        h = AgentHarness.create(tmp_path, settings_overrides=ALLOW, fetcher=LocalDirectorySourceFetcher(root))
        # 取得資格はテストの偽のコアが "srcsecret-0001-..." の形で発行する。ツールがそれを出力しても、マスクされる。
        job_id = h.core.enqueue(
            "type-a", payload("print-raw", "srcsecret-0001-0123456789abcdef"), source="sample-repo", revision="abc123"
        )
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        assert "srcsecret-0001" not in h.core.log_text(job_id) and "***" in h.core.log_text(job_id)

    asyncio.run(scenario())


def test_fetch_failure_is_reported_as_source_unavailable(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = make_sources(tmp_path)
        h = AgentHarness.create(tmp_path, settings_overrides=ALLOW, fetcher=LocalDirectorySourceFetcher(root))
        missing = h.core.enqueue("type-a", payload("echo", "x"), source="sample-repo", revision="no-such-revision")
        h.start()
        await h.wait_for(lambda: h.core.jobs[missing].state == "failed")
        await h.shutdown()
        report = h.core.jobs[missing].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "source_unavailable" and h.work_root_entries() == []

    asyncio.run(scenario())


def test_no_credential_issuer_or_no_fetcher_is_source_unavailable(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = make_sources(tmp_path)
        h = AgentHarness.create(tmp_path, settings_overrides=ALLOW, fetcher=LocalDirectorySourceFetcher(root))
        h.core.source_credentials_enabled = False
        a = h.core.enqueue("type-a", payload("echo", "x"), source="sample-repo", revision="abc123")
        h.start()
        await h.wait_for(lambda: h.core.jobs[a].state == "failed")
        await h.shutdown()
        report: Any = h.core.jobs[a].report
        assert report.failure_reason.value == "source_unavailable"

        h2 = AgentHarness.create(tmp_path / "second", settings_overrides=ALLOW)  # 取得の実装が構成されていない
        b = h2.core.enqueue("type-a", payload("echo", "x"), source="sample-repo", revision="abc123")
        h2.start()
        await h2.wait_for(lambda: h2.core.jobs[b].state == "failed")
        await h2.shutdown()
        report2: Any = h2.core.jobs[b].report
        assert report2.failure_reason.value == "source_unavailable"

    asyncio.run(scenario())
