#!/usr/bin/env python3
"""Run a Copilot CLI print-mode task and record its token usage into SQLite.

Usage:
    copilot-track.py "your prompt here"
    copilot-track.py --model gpt-5.4 --task "short label" "your prompt here"

Wraps `copilot -p ...`, prints the response as usual, and records one row per
call — no behavior change for the caller beyond that.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.copilot_cli_runner import CopilotCliRunner
from adapters.sqlite_usage_store import SqliteUsageStore
from core.model import TaskCall


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    parser.add_argument("--model", default="auto")
    parser.add_argument("--task", default="", help="Short label for this call, defaults to the prompt")
    args = parser.parse_args()

    runner = CopilotCliRunner()
    store = SqliteUsageStore()
    try:
        start = datetime.now(timezone.utc)
        result = runner.run_task(args.prompt, model=args.model)
        duration_s = (datetime.now(timezone.utc) - start).total_seconds()

        store.record_task_call(
            TaskCall(
                timestamp=start.isoformat(),
                model=result.resolved_model or args.model,
                status=result.status,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                thinking_tokens=result.thinking_tokens,
                total_tokens=result.total_tokens,
                duration_s=duration_s,
                task=(args.task or args.prompt)[:200],
                cache_read_tokens=result.cache_read_tokens,
                cache_creation_tokens=result.cache_creation_tokens,
                source="copilot",
            )
        )
        print(result.response)
    finally:
        store.close()


if __name__ == "__main__":
    main()
