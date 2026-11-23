"""状態フォルダのジャーナルと、エージェントの監査(data-model.md §2・§2.1)。

書き込みは一時ファイル + 置き換えで原子的に行う。監査の項目は固定の語彙 + 数値で、
ログ本文・環境変数の値・資格・payload の値を含めない。
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

AUDIT_EVENTS = frozenset(
    {
        "path_rejected",
        "mask_applied",
        "repository_rejected",
        "tool_not_registered",
        "env_name_rejected",
        "artifact_pattern_rejected",
        "artifact_limit",
        "artifact_store_disabled",
        "fault_signal_rejected",
        "work_folder_cleanup_failed",
        "report_rejected",
        "stopped",
        "executor_error",
        "agent_restarted",
    }
)
_DETAIL_KEYS = frozenset({"kind", "index", "count", "reason", "status", "code", "text"})
MAX_TEXT = 200


class AgentJournal:
    def __init__(self, state_dir: str | Path, retention_days: int = 90) -> None:
        self.root = Path(state_dir)
        self.retention_days = retention_days
        for name in ("journal/results", "spool", "audit"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ 原子的な書き込み

    @staticmethod
    def _write_atomic(path: Path, data: Mapping[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    # ------------------------------------------------------------------ active.json

    def write_active(self, job_id: str, lease_id: str, started_at: str) -> None:
        self._write_atomic(
            self.root / "journal" / "active.json",
            {"job_id": job_id, "lease_id": lease_id, "started_at": started_at},
        )

    def read_active(self) -> dict[str, Any] | None:
        path = self.root / "journal" / "active.json"
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def clear_active(self) -> None:
        (self.root / "journal" / "active.json").unlink(missing_ok=True)

    # ------------------------------------------------------------------ 未報告の結果

    def save_result(self, job_id: str, report: Mapping[str, Any]) -> None:
        self._write_atomic(self._result_path(job_id), {"job_id": job_id, "report": dict(report)})

    def load_results(self) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        for path in sorted((self.root / "journal" / "results").glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                out.append((str(data["job_id"]), dict(data["report"])))
            except (OSError, ValueError, KeyError):
                continue
        return out

    def remove_result(self, job_id: str) -> None:
        self._result_path(job_id).unlink(missing_ok=True)

    def _result_path(self, job_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in job_id)[:120]
        return self.root / "journal" / "results" / f"{safe}.json"

    # ------------------------------------------------------------------ 監査(ローカル)

    def audit(self, event: str, job_id: str | None = None, **detail: Any) -> None:
        if event not in AUDIT_EVENTS:
            raise ValueError("未知の監査の種類")
        clean: dict[str, Any] = {}
        for key, value in detail.items():
            if key not in _DETAIL_KEYS:
                raise ValueError("未知の詳細の項目")
            if isinstance(value, bool | int):
                clean[key] = value
            elif isinstance(value, str):
                clean[key] = value[:MAX_TEXT]
            else:
                raise ValueError("詳細は数値・真偽・短い文字列に限る")
        now = datetime.now(UTC)
        record = {"at": now.isoformat(), "job_id": job_id, "event": event, **clean}
        path = self.root / "audit" / f"agent-audit-{now:%Y%m%d}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_audit(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted((self.root / "audit").glob("agent-audit-*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
        return records

    def purge_old_audit(self, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=self.retention_days)
        removed = 0
        for path in (self.root / "audit").glob("agent-audit-*.jsonl"):
            try:
                day = datetime.strptime(path.stem.removeprefix("agent-audit-"), "%Y%m%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            if day < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def now_text(self) -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def monotonic() -> float:
        return time.monotonic()
