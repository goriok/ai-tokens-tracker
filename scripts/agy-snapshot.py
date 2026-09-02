#!/usr/bin/env python3
"""Record a zero-cost snapshot of agy's weekly quota (`/usage`) into SQLite.

Meant to run on a timer (cron/systemd) — each run is one data point per
model group, letting later analysis diff snapshots to approximate
consumption over any period, TUI usage included (quota reflects all
account activity, not just -p calls).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.agy_cli_runner import AgyCliRunner
from adapters.sqlite_usage_store import SqliteUsageStore


def main() -> None:
    runner = AgyCliRunner()
    store = SqliteUsageStore()
    try:
        snapshots = runner.fetch_usage()
        if not snapshots:
            print("No usage groups in response — agy CLI output may have changed.", file=sys.stderr)
            sys.exit(1)
        for snapshot in snapshots:
            store.record_snapshot(snapshot)
        print(f"✓ {len(snapshots)} snapshot(s) recorded at {snapshots[0].timestamp}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
