from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from core.model import TaskCall, UsageSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    model_group TEXT NOT NULL,
    remaining_fraction REAL NOT NULL,
    reset_time TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_snapshots_timestamp ON usage_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_snapshots_group ON usage_snapshots(model_group);

CREATE TABLE IF NOT EXISTS task_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    thinking_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    duration_s REAL NOT NULL DEFAULT 0,
    task TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_task_calls_timestamp ON task_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_task_calls_model ON task_calls(model);
"""

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "agy-tracker" / "usage.db"


class SqliteUsageStore:
    """UsageStore adapter backed by a local SQLite file."""

    def __init__(self, db_path: Path | None = None) -> None:
        env_path = os.environ.get("AGY_TOOL_DB")
        self._path = db_path or (Path(env_path) if env_path else DEFAULT_DB_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._conn = sqlite3.connect(self._path)
        self._conn.executescript(SCHEMA)
        os.chmod(self._path, 0o600)  # idempotent — also tightens pre-existing files

    def record_snapshot(self, snapshot: UsageSnapshot) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO usage_snapshots (timestamp, model_group, remaining_fraction, reset_time)"
                " VALUES (?, ?, ?, ?)",
                (snapshot.timestamp, snapshot.model_group, snapshot.remaining_fraction, snapshot.reset_time),
            )

    def record_task_call(self, call: TaskCall) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO task_calls"
                " (timestamp, model, status, input_tokens, output_tokens, thinking_tokens, total_tokens, duration_s, task)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    call.timestamp,
                    call.model,
                    call.status,
                    call.input_tokens,
                    call.output_tokens,
                    call.thinking_tokens,
                    call.total_tokens,
                    call.duration_s,
                    call.task,
                ),
            )

    def list_snapshots(self) -> list[UsageSnapshot]:
        cur = self._conn.execute(
            "SELECT timestamp, model_group, remaining_fraction, reset_time"
            " FROM usage_snapshots ORDER BY timestamp"
        )
        return [UsageSnapshot(*row) for row in cur.fetchall()]

    def list_task_calls(self) -> list[TaskCall]:
        cur = self._conn.execute(
            "SELECT timestamp, model, status, input_tokens, output_tokens, thinking_tokens,"
            " total_tokens, duration_s, task FROM task_calls ORDER BY timestamp"
        )
        return [TaskCall(*row) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
