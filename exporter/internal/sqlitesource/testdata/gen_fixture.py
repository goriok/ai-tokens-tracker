#!/usr/bin/env python3
"""Regenerate fixture.db using the real Python schema (SqliteUsageStore) —
keeps the Go test fixture honest against adapters/sqlite_usage_store.py
instead of a hand-copied CREATE TABLE. Run from the exporter dir:

    uv run --project .. python3 internal/sqlitesource/testdata/gen_fixture.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from adapters.sqlite_usage_store import SqliteUsageStore
from core.model import ClaudeCodeUsageEvent, CopilotUsageEvent, TaskCall, UsageSnapshot

FIXTURE_PATH = Path(__file__).resolve().parent / "fixture.db"


def main() -> None:
    FIXTURE_PATH.unlink(missing_ok=True)
    store = SqliteUsageStore(db_path=FIXTURE_PATH)

    # Two ordinary claude-code events, one main-agent, one subagent.
    store.record_claude_code_event(
        ClaudeCodeUsageEvent(
            timestamp="2026-09-01T10:00:00.123Z",
            session_id="sess-1",
            project_slug="proj-a",
            cwd="/home/user/proj-a",
            git_branch="main",
            model="claude-sonnet-5",
            request_id="req-1",
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=10,
            cache_creation_input_tokens=5,
        )
    )
    store.record_claude_code_event(
        ClaudeCodeUsageEvent(
            timestamp="2026-09-01T10:05:00.456Z",
            session_id="sess-1",
            project_slug="proj-a",
            cwd="/home/user/proj-a",
            git_branch="main",
            model="claude-opus-5",
            request_id="req-2",
            input_tokens=200,
            output_tokens=80,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            agent_id="agent-xyz",
        )
    )
    # A row inserted later but timestamped earlier — the out-of-order case
    # that makes id-ordered (not timestamp-ordered) cursoring mandatory.
    store.record_claude_code_event(
        ClaudeCodeUsageEvent(
            timestamp="2026-08-15T09:00:00.000Z",
            session_id="sess-0",
            project_slug="proj-b",
            cwd=None,
            git_branch=None,
            model="claude-haiku-4-5-20251001",
            request_id="req-3-late-discovery",
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
    )

    store.record_copilot_event(
        CopilotUsageEvent(
            timestamp="2026-09-01T11:00:00.789Z",
            session_id="copilot-sess-1",
            cwd="/home/user/proj-c",
            model="gpt-5.6-sol",
            input_tokens=300,
            output_tokens=120,
            cache_read_tokens=20,
            cache_creation_tokens=15,
        )
    )

    store.record_task_call(
        TaskCall(
            timestamp="2026-09-01T12:00:00.111111+00:00",
            model="claude-sonnet-5",
            status="ok",
            input_tokens=40,
            output_tokens=20,
            thinking_tokens=0,
            total_tokens=60,
            duration_s=1.5,
            task="test task",
            cache_read_tokens=5,
            source="agy",
            cache_creation_tokens=0,
            confidence_score=None,
        )
    )
    store.record_task_call(
        TaskCall(
            timestamp="2026-09-01T12:05:00.222222+00:00",
            model="gpt-5.6-luna",
            status="ok",
            input_tokens=70,
            output_tokens=30,
            thinking_tokens=0,
            total_tokens=100,
            duration_s=2.0,
            task="another task",
            cache_read_tokens=8,
            source="copilot",
            cache_creation_tokens=3,
            confidence_score=8.5,
        )
    )

    store.record_snapshot(
        UsageSnapshot(
            timestamp="2026-09-01T13:00:00.000Z",
            model_group="gpt-5",
            remaining_fraction=0.42,
            reset_time="2026-09-08T00:00:00Z",
        )
    )

    store.close()
    print(f"wrote {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
