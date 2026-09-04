from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from core.model import ClaudeCodeUsageEvent, TaskCall, UsageSnapshot

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

CREATE TABLE IF NOT EXISTS claude_code_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    project_slug TEXT NOT NULL,
    cwd TEXT,
    git_branch TEXT,
    model TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cc_usage_timestamp ON claude_code_usage_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_cc_usage_model ON claude_code_usage_events(model);
CREATE INDEX IF NOT EXISTS idx_cc_usage_project ON claude_code_usage_events(project_slug);

CREATE TABLE IF NOT EXISTS claude_code_read_cursors (
    file_path TEXT PRIMARY KEY,
    byte_offset INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "ai-tokens-tracker" / "usage.db"


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

    def record_claude_code_event(self, event: ClaudeCodeUsageEvent) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO claude_code_usage_events"
                " (timestamp, session_id, project_slug, cwd, git_branch, model, request_id,"
                " input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.timestamp,
                    event.session_id,
                    event.project_slug,
                    event.cwd,
                    event.git_branch,
                    event.model,
                    event.request_id,
                    event.input_tokens,
                    event.output_tokens,
                    event.cache_read_input_tokens,
                    event.cache_creation_input_tokens,
                ),
            )

    def list_claude_code_events(self) -> list[ClaudeCodeUsageEvent]:
        cur = self._conn.execute(
            "SELECT timestamp, session_id, project_slug, cwd, git_branch, model, request_id,"
            " input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens"
            " FROM claude_code_usage_events ORDER BY timestamp"
        )
        return [ClaudeCodeUsageEvent(*row) for row in cur.fetchall()]

    def get_claude_code_cursor(self, file_path: str) -> int:
        cur = self._conn.execute(
            "SELECT byte_offset FROM claude_code_read_cursors WHERE file_path = ?", (file_path,)
        )
        row = cur.fetchone()
        return row[0] if row else 0

    def set_claude_code_cursor(self, file_path: str, byte_offset: int) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO claude_code_read_cursors (file_path, byte_offset) VALUES (?, ?)"
                " ON CONFLICT(file_path) DO UPDATE SET byte_offset = excluded.byte_offset",
                (file_path, byte_offset),
            )

    def close(self) -> None:
        self._conn.close()
