#!/usr/bin/env python3
"""Delegate a task to agy, picking the model automatically.

Usage:
    agy-delegate.py --complexity low "your prompt here"
    agy-delegate.py --complexity high --task "refactor auth module" "your prompt here"
    agy-delegate.py --model gemini-3.7-flash-low "your prompt here"  # skip auto-pick

Complexity guide (see core/model_policy.py):
    low    — routine, single-step (Q&A, small edits, lookups)
    medium — standard coding/debugging, a few files
    high   — architecture, multi-file refactors, hard debugging

Picks a model for the given complexity, steering away from a model group
whose weekly quota (from the latest recorded /usage snapshot) is running
low, then runs the task via `agy -p` and records it like agy-track.py does.
Run agy-snapshot.py first (or on a timer) so the quota data used here is
fresh — this does not poll /usage itself, to keep this a single real model
call per invocation.
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
from core.model_policy import choose_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt")
    parser.add_argument("--complexity", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--model", help="Skip auto-pick and use this model directly")
    parser.add_argument("--task", default="", help="Short label for this call, defaults to the prompt")
    parser.add_argument("--effort")
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    args = parser.parse_args()

    store = SqliteUsageStore()
    try:
        if args.model:
            model = args.model
        else:
            snapshots = store.list_snapshots()
            model = choose_model(args.complexity, snapshots)
            print(f"[agy-delegate] complexity={args.complexity} -> model={model}", file=sys.stderr)

        runner = AgyCliRunner()
        start = datetime.now(timezone.utc)
        result = runner.run_task(
            args.prompt,
            model=model,
            effort=args.effort,
            skip_permissions=args.dangerously_skip_permissions,
        )
        duration_s = (datetime.now(timezone.utc) - start).total_seconds()

        store.record_task_call(
            TaskCall(
                timestamp=start.isoformat(),
                model=model,
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
