"""ジャーナルとローカルの監査(T019)。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_runner_agent.journal import AgentJournal


def test_active_and_results_roundtrip_and_survive_new_instance(tmp_path: Path) -> None:
    journal = AgentJournal(tmp_path)
    assert journal.read_active() is None
    journal.write_active("job-1", "lease-1", "2026-11-22T00:00:00Z")
    journal.save_result("job-1", {"outcome": "failed"})
    again = AgentJournal(tmp_path)
    assert again.read_active() == {"job_id": "job-1", "lease_id": "lease-1", "started_at": "2026-11-22T00:00:00Z"}
    assert again.load_results() == [("job-1", {"outcome": "failed"})]
    again.remove_result("job-1")
    again.clear_active()
    assert again.load_results() == [] and again.read_active() is None
    again.remove_result("job-1")  # 冪等


def test_no_temporary_files_remain_and_names_are_confined(tmp_path: Path) -> None:
    journal = AgentJournal(tmp_path)
    journal.save_result("job/../1", {"outcome": "succeeded"})
    assert not list(tmp_path.rglob("*.tmp"))
    results = tmp_path / "journal" / "results"
    assert all(p.parent == results for p in results.iterdir())


def test_audit_records_fixed_vocabulary_only(tmp_path: Path) -> None:
    journal = AgentJournal(tmp_path)
    journal.audit("path_rejected", "job-1", kind="parent", index=2, text="..\\x" * 200)
    record = journal.read_audit()[0]
    assert record["event"] == "path_rejected" and record["kind"] == "parent" and len(record["text"]) == 200
    with pytest.raises(ValueError):
        journal.audit("unknown_event")
    with pytest.raises(ValueError):
        journal.audit("mask_applied", "job-1", secret_value="x")  # 未知の項目
    with pytest.raises(ValueError):
        journal.audit("mask_applied", "job-1", count=[1])  # 構造のある値は不可


def test_purge_old_audit(tmp_path: Path) -> None:
    journal = AgentJournal(tmp_path, retention_days=90)
    old = tmp_path / "audit" / "agent-audit-20200101.jsonl"
    old.write_text("{}\n")
    journal.audit("stopped", "j", reason="abort")
    assert journal.purge_old_audit(datetime.now(UTC)) == 1
    assert not old.exists() and journal.read_audit()
    assert journal.purge_old_audit(datetime.now(UTC) + timedelta(days=200)) == 1
