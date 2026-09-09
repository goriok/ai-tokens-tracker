#!/usr/bin/env python3
"""Record new Copilot CLI token usage events into SQLite.

Reads ~/.copilot/session-state/*/events.jsonl (zero-cost — local files
already written by the Copilot CLI, no CLI call, covers interactive/TUI use
and -p calls made outside copilot-track.py alike), deduplicates by
session_id, and records any completed session (session.shutdown present)
not seen before. Safe to run frequently (e.g. every few minutes via
cron/systemd timer) — a session with no shutdown event yet is skipped until
a future run finds it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.copilot_transcript_reader import CopilotTranscriptReader
from adapters.sqlite_usage_store import SqliteUsageStore


def main() -> None:
    store = SqliteUsageStore()
    try:
        reader = CopilotTranscriptReader(store)
        events = reader.read_new_events()
        for event in events:
            store.record_copilot_event(event)
        print(f"✓ {len(events)} new event(s) recorded")
    finally:
        store.close()


if __name__ == "__main__":
    main()
