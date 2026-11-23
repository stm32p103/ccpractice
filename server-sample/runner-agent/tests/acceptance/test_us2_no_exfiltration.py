"""US2: 機密情報を持ち出さない(spec US2-1〜US2-6。V6〜V11。SC-002〜SC-004)。

仕様の受け入れ基準のうち「作業フォルダ外のファイルを、ツール自体が読もうとする」場合の防御は、OS の権限(
ツール用の別アカウントと ACL)
であり、同じアカウントで動かす dev の DirectLauncher では保証しない(`-m twoaccount` の test_us6_twoaccount.py
で検査する)。
ここでは、エージェントの責務(環境変数の非継承、秘密のマスク、パスの検査、成果物の収集範囲、書き出しの範囲)を検査する。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from job_testing.runner_fakes.executors import payload
from job_testing.runner_fakes.harness import AgentHarness
from job_testing.runner_fakes.recording_server import socket_watch

DUMMY = "dummy-secret-0123456789"


def test_us2_1_us2_2_parent_environment_and_agent_token_are_not_visible_to_the_tool(tmp_path: Path) -> None:
    os.environ["PARENT_DUMMY_SECRET"] = DUMMY
    try:

        async def scenario() -> None:
            h = AgentHarness.create(tmp_path)
            job_id = h.core.enqueue("type-a", payload("env"))
            h.start()
            await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
            await h.shutdown()
            seen = json.loads(h.core.log_text(job_id))
            names = {name.upper() for name in seen}
            assert names == {"SYSTEMROOT", "TEMP", "TMP", "JOB_WORK_DIR", "JOB_SIGNAL_DIR"}
            everything = h.core.log_text(job_id) + h.core.recorded_text()
            assert DUMMY not in everything
            assert h.core.token not in h.core.log_text(job_id)

        asyncio.run(scenario())
    finally:
        del os.environ["PARENT_DUMMY_SECRET"]


@pytest.mark.parametrize(
    ("bad", "kind"),
    [
        ("..\\outside.txt", "parent"),
        ("C:\\Windows\\win.ini", "drive"),
        ("\\\\server\\share\\f", "unc"),
        ("\\\\?\\C:\\x", "device"),
        ("file.txt:stream", "stream"),
        ("work\\..\\..\\x", "parent"),
        ("NUL", "reserved"),
    ],
)
def test_us2_3_path_escape_is_rejected_and_audited(tmp_path: Path, bad: str, kind: str) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        job_id = h.core.enqueue("type-a", payload("write-file", {"work": bad}, "x"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "input_rejected" and report.exit_code is None
        assert report.counters.path_rejections == 1
        assert h.core.log_text(job_id) == ""  # ツールは起動されない
        events = [r for r in h.journal.read_audit() if r["event"] == "path_rejected"]
        assert len(events) == 1 and events[0]["kind"] == kind and events[0]["job_id"] == job_id
        assert h.work_root_entries() == []

    asyncio.run(scenario())


@pytest.mark.windows
def test_us2_3_junction_in_source_is_rejected(tmp_path: Path) -> None:
    import subprocess

    async def scenario() -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("OUTSIDE-SECRET")
        h = AgentHarness.create(tmp_path)
        # 1 件目: ツールが作業フォルダ内にジャンクションを作る。2 件目: そのジャンクション越しのパスを要求する(
        # 同じ作業フォルダではない)
        folder_hint: list[Path] = []

        class Executor:
            def prepare(self, ctx):  # type: ignore[no-untyped-def]
                junction = ctx.work.root / "work" / "junc"
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], check=True, capture_output=True
                )
                folder_hint.append(junction)
                ctx.work.resolve("work\\junc\\secret.txt")  # リパースポイントの拒否
                raise AssertionError("到達しない")

            def interpret(self, ctx, outcome):  # type: ignore[no-untyped-def]
                raise AssertionError

        h.context.executors = {"type-a": Executor()}
        job_id = h.core.enqueue("type-a", payload("echo", "x"))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.counters.path_rejections == 1
        assert (outside / "secret.txt").read_text() == "OUTSIDE-SECRET"  # 削除でリンク先を辿らない
        assert [r["kind"] for r in h.journal.read_audit() if r["event"] == "path_rejected"] == ["reparse_point"]

    asyncio.run(scenario())


def test_us2_4_only_ledger_destinations_and_contents_are_sent(tmp_path: Path) -> None:
    async def scenario() -> None:
        with socket_watch() as connections:
            h = AgentHarness.create(tmp_path, artifact_dir=tmp_path / "results")
            job_id = h.core.enqueue(
                "type-a",
                payload("write-file", {"work": "work\\out\\r.txt"}, "BODY-OF-ARTIFACT", patterns=["work\\out\\*.txt"]),
            )
            h.start()
            await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
            await h.shutdown()
        assert connections == []  # 外向きの接続が 0 件
        assert h.recorder is not None
        assert h.recorder.hosts == {"fake-core.invalid"}
        allowed_paths = {
            "/v1/runner/registration",
            "/v1/runner/heartbeat",
            "/v1/runner/job-requests",
            f"/v1/runner/jobs/{job_id}/logs",
            f"/v1/runner/jobs/{job_id}/result",
        }
        assert {item.path for item in h.recorder.sent} <= allowed_paths
        assert "BODY-OF-ARTIFACT" not in h.recorder.text()  # 成果物の中身はコアを通らない
        for item in h.recorder.sent:
            if item.path.endswith("/result"):
                assert set(item.body) <= {
                    "outcome",
                    "result_summary",
                    "exit_code",
                    "failure_reason",
                    "artifacts",
                    "counters",
                }

    asyncio.run(scenario())


def test_us2_5_secrets_in_logs_are_masked_and_counted(tmp_path: Path) -> None:
    pem = "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----"

    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        token = h.core.token
        job_id = h.core.enqueue(
            "type-a",
            payload("print-raw", f"agent-token={token}", "ghp_0123456789abcdefghijABCDEFGHIJ", "plain line", pem),
        )
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        text = h.core.log_text(job_id)
        for secret in (token, "ghp_0123456789", "MIIBVgIBADANBgkq"):
            assert secret not in text
        assert "plain line" in text and "***" in text
        report = h.core.jobs[job_id].report
        assert report is not None and report.counters.masked_lines >= 3
        audit_text = json.dumps(h.journal.read_audit())
        assert token not in audit_text and "ghp_" not in audit_text

    asyncio.run(scenario())


def test_us2_6_only_pattern_matching_regular_files_are_collected(tmp_path: Path) -> None:
    async def scenario() -> None:
        store_dir = tmp_path / "results"
        h = AgentHarness.create(tmp_path, artifact_dir=store_dir)
        sneaky = tmp_path / "outside-data.txt"
        sneaky.write_text("OUTSIDE")
        job_id = h.core.enqueue(
            "type-a",
            payload("write-file", {"work": "work\\out\\keep.txt"}, "KEEP", patterns=["work\\out\\*.txt"]),
        )
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and [a.name for a in report.artifacts] == ["keep.txt"]
        artifact = report.artifacts[0]
        assert artifact.kind.value == "unc" and artifact.reference == f"\\\\runner-pc\\results\\{job_id}\\keep.txt"
        stored = store_dir / job_id / "keep.txt"
        assert stored.read_text() == "KEEP" and artifact.size_bytes == 4
        assert not (store_dir / job_id / "outside-data.txt").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("pattern", ["..\\outside\\*", "C:\\x\\*", "\\\\h\\s\\*", "work\\..\\*"])
def test_us2_6_patterns_escaping_the_work_folder_are_rejected(tmp_path: Path, pattern: str) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path, artifact_dir=tmp_path / "results")
        job_id = h.core.enqueue("type-a", payload("echo", "x", patterns=[pattern]))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "input_rejected" and report.counters.path_rejections == 1
        assert not (tmp_path / "results" / job_id).exists()

    asyncio.run(scenario())


def test_us2_6_limits_exceeded_fail_without_collecting(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path, artifact_dir=tmp_path / "results", artifact_limits={"max_file_bytes": 10})
        job_id = h.core.enqueue(
            "type-a", payload("write-big", {"work": "work\\big.bin"}, "100", patterns=["work\\*.bin"])
        )
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "failed")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.failure_reason is not None
        assert report.failure_reason.value == "artifact_limit_exceeded" and report.artifacts == ()
        assert not list((tmp_path / "results").rglob("*.bin"))
        assert any(r["event"] == "artifact_limit" for r in h.journal.read_audit())

    asyncio.run(scenario())


def test_artifacts_disabled_by_default_collect_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)  # artifact_store は disabled
        job_id = h.core.enqueue("type-a", payload("write-file", {"work": "work\\a.txt"}, "A", patterns=["work\\*.txt"]))
        h.start()
        await h.wait_for(lambda: h.core.jobs[job_id].state == "succeeded")
        await h.shutdown()
        report = h.core.jobs[job_id].report
        assert report is not None and report.artifacts == ()
        assert any(r["event"] == "artifact_store_disabled" for r in h.journal.read_audit())

    asyncio.run(scenario())


def test_tool_not_in_registry_or_env_not_allowed_is_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        h = AgentHarness.create(tmp_path)
        unknown_tool = h.core.enqueue("type-a", payload("echo", "x", tool_id="C:\\Windows\\System32\\cmd.exe"))
        bad_env = h.core.enqueue("type-a", payload("echo", "x", env={"EVIL_VAR": "1"}))
        h.start()
        await h.wait_for(lambda: all(h.core.jobs[j].state == "failed" for j in (unknown_tool, bad_env)))
        await h.shutdown()
        for job_id in (unknown_tool, bad_env):
            report = h.core.jobs[job_id].report
            assert report is not None and report.failure_reason is not None
            assert report.failure_reason.value == "input_rejected" and h.core.log_text(job_id) == ""
        events = {r["event"] for r in h.journal.read_audit()}
        assert {"tool_not_registered", "env_name_rejected"} <= events

    asyncio.run(scenario())
