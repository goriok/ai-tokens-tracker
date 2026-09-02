#!/usr/bin/env python3
"""Run an agy print-mode task and record its token usage into SQLite.

Usage:
    agy-track.py --model gemini-3.7-flash-low "your prompt here"
    agy-track.py --model gemini-3.7-flash-low --task "short label" "your prompt here"

Wraps `agy -p ... --output-format json`, prints the response as usual, and
records one row per call — no behavior change for the caller beyond that.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.agy_cli_runner import AgyCliRunner
from adapters.sqlite_usage_store import SqliteUsageStore
from core.model import TaskCall


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    parser.add_argument("--model", required=True)
    parser.add_argument("--task", default="", help="Short label for this call, defaults to the prompt")
    parser.add_argument("--effort")
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    args = parser.parse_args()

    runner = AgyCliRunner()
    store = SqliteUsageStore()
    try:
        start = datetime.now(timezone.utc)
        result = runner.run_task(
            args.prompt,
            model=args.model,
            effort=args.effort,
            skip_permissions=args.dangerously_skip_permissions,
        )
        duration_s = (datetime.now(timezone.utc) - start).total_seconds()

        store.record_task_call(
            TaskCall(
                timestamp=start.isoformat(),
                model=args.model,
                status=result.status,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                thinking_tokens=result.thinking_tokens,
                total_tokens=result.total_tokens,
                duration_s=duration_s,
                task=(args.task or args.prompt)[:200],
            )
        )
        print(result.response)
    finally:
        store.close()


if __name__ == "__main__":
    main()
