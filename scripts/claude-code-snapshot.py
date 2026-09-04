#!/usr/bin/env python3
"""Record new Claude Code token usage events into SQLite.

Reads ~/.claude/projects/**/*.jsonl (zero-cost — local files already written
by Claude Code, no CLI call, covers interactive and non-interactive usage
alike), deduplicates by requestId, and records any events not seen before.
Incremental via a per-file byte-offset cursor — safe to run frequently
(e.g. every few minutes via cron/systemd timer).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.claude_code_transcript_reader import ClaudeCodeTranscriptReader
from adapters.sqlite_usage_store import SqliteUsageStore


def main() -> None:
    store = SqliteUsageStore()
    try:
        reader = ClaudeCodeTranscriptReader(store)
        events = reader.read_new_events()
        for event in events:
            store.record_claude_code_event(event)
        print(f"✓ {len(events)} new event(s) recorded")
    finally:
        store.close()


if __name__ == "__main__":
    main()
