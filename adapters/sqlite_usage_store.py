from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from core.model import ClaudeCodeUsageEvent, CopilotUsageEvent, SessionTitle, TaskCall, UsageSnapshot

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
    task TEXT NOT NULL DEFAULT '',
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'agy',
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    confidence_score REAL
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
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    agent_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_cc_usage_timestamp ON claude_code_usage_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_cc_usage_model ON claude_code_usage_events(model);
CREATE INDEX IF NOT EXISTS idx_cc_usage_project ON claude_code_usage_events(project_slug);

CREATE TABLE IF NOT EXISTS claude_code_read_cursors (
    file_path TEXT PRIMARY KEY,
    byte_offset INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS session_titles (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS copilot_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    cwd TEXT,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_copilot_usage_timestamp ON copilot_usage_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_copilot_usage_model ON copilot_usage_events(model);

CREATE TABLE IF NOT EXISTS copilot_read_sessions (
    session_id TEXT PRIMARY KEY
);
"""

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "ai-tokens-tracker" / "usage.db"


class SqliteUsageStore:
    """UsageStore adapter backed by a local SQLite file."""

    def __init__(self, db_path: Path | None = None) -> None:
        env_path = os.environ.get("AGY_TOOL_DB")
        self._path = db_path or (Path(env_path) if env_path else DEFAULT_DB_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # check_same_thread=False: the dashboard server serves each request from
        # a threadpool worker: SQLite itself serializes access, and each call
        # here is a short-lived read/write with no cross-request shared state.
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        # WAL instead of the default rollback journal: lets a read-only external
        # reader (the Go exporter) query concurrently without blocking on — or
        # blocking — these writes. Persists in the db file, so this only needs
        # to run once per file, but it's cheap and idempotent to set every open.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        self._migrate()
        # WAL mode means data can live in -wal/-shm sidecar files (created with
        # the process umask, typically world-readable) before a checkpoint moves
        # it into usage.db — chmod all three, not just the main file, or an
        # uncommitted write sits world-readable next to a 0600 empty-looking db.
        for suffix in ("", "-wal", "-shm"):
            sidecar = self._path.with_name(self._path.name + suffix)
            if sidecar.exists():
                os.chmod(sidecar, 0o600)

    def _migrate(self) -> None:
        # ALTER TABLE ADD COLUMN has no IF NOT EXISTS — added after claude_code_usage_events
        # already shipped, so pre-existing databases need this instead of a fresh CREATE TABLE.
        try:
            with self._conn:
                self._conn.execute("ALTER TABLE claude_code_usage_events ADD COLUMN agent_id TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cc_usage_agent ON claude_code_usage_events(agent_id)"
        )
        try:
            with self._conn:
                self._conn.execute(
                    "ALTER TABLE task_calls ADD COLUMN cache_read_tokens INTEGER NOT NULL DEFAULT 0"
                )
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
        try:
            with self._conn:
                self._conn.execute(
                    "ALTER TABLE task_calls ADD COLUMN source TEXT NOT NULL DEFAULT 'agy'"
                )
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_task_calls_source ON task_calls(source)")
        try:
            with self._conn:
                self._conn.execute(
                    "ALTER TABLE task_calls ADD COLUMN cache_creation_tokens INTEGER NOT NULL DEFAULT 0"
                )
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
        try:
            with self._conn:
                self._conn.execute("ALTER TABLE task_calls ADD COLUMN confidence_score REAL")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise

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
                " (timestamp, model, status, input_tokens, output_tokens, thinking_tokens, total_tokens,"
                " duration_s, task, cache_read_tokens, source, cache_creation_tokens, confidence_score)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    call.cache_read_tokens,
                    call.source,
                    call.cache_creation_tokens,
                    call.confidence_score,
                ),
            )

    def update_task_call_confidence_score(self, task: str, confidence_score: float) -> None:
        """Fills in confidence_score after the fact — set at record_task_call
        time the score isn't known yet (confidence-analysis hasn't run).
        Matches by task label; if the same label was used more than once,
        every matching row is updated (labels are expected unique per
        round-prefix convention)."""
        with self._conn:
            self._conn.execute(
                "UPDATE task_calls SET confidence_score = ? WHERE task = ?",
                (confidence_score, task),
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
            " total_tokens, duration_s, task, cache_read_tokens, source, cache_creation_tokens,"
            " confidence_score"
            " FROM task_calls ORDER BY timestamp"
        )
        return [TaskCall(*row) for row in cur.fetchall()]

    def record_claude_code_event(self, event: ClaudeCodeUsageEvent) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO claude_code_usage_events"
                " (timestamp, session_id, project_slug, cwd, git_branch, model, request_id,"
                " input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens,"
                " agent_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    event.agent_id,
                ),
            )

    def list_claude_code_events(self) -> list[ClaudeCodeUsageEvent]:
        cur = self._conn.execute(
            "SELECT timestamp, session_id, project_slug, cwd, git_branch, model, request_id,"
            " input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens,"
            " agent_id"
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

    def record_session_title(self, title: SessionTitle) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO session_titles (session_id, title) VALUES (?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET title = excluded.title",
                (title.session_id, title.title),
            )

    def list_session_titles(self) -> list[SessionTitle]:
        cur = self._conn.execute("SELECT session_id, title FROM session_titles")
        return [SessionTitle(*row) for row in cur.fetchall()]

    def record_copilot_event(self, event: CopilotUsageEvent) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO copilot_usage_events"
                " (timestamp, session_id, cwd, model, input_tokens, output_tokens,"
                " cache_read_tokens, cache_creation_tokens)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.timestamp,
                    event.session_id,
                    event.cwd,
                    event.model,
                    event.input_tokens,
                    event.output_tokens,
                    event.cache_read_tokens,
                    event.cache_creation_tokens,
                ),
            )

    def list_copilot_events(self) -> list[CopilotUsageEvent]:
        cur = self._conn.execute(
            "SELECT timestamp, session_id, cwd, model, input_tokens, output_tokens,"
            " cache_read_tokens, cache_creation_tokens"
            " FROM copilot_usage_events ORDER BY timestamp"
        )
        return [CopilotUsageEvent(*row) for row in cur.fetchall()]

    def is_copilot_session_read(self, session_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM copilot_read_sessions WHERE session_id = ?", (session_id,)
        )
        return cur.fetchone() is not None

    def mark_copilot_session_read(self, session_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO copilot_read_sessions (session_id) VALUES (?)",
                (session_id,),
            )

    def close(self) -> None:
        self._conn.close()
