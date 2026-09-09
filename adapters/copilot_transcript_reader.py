from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from adapters.sqlite_usage_store import SqliteUsageStore
from core.model import CopilotUsageEvent

DEFAULT_SESSION_STATE_DIR = Path.home() / ".copilot" / "session-state"


class CopilotTranscriptReader:
    """CopilotTranscriptReader adapter backed by local session-state/events.jsonl
    files the Copilot CLI writes automatically — the zero-cost counterpart to a
    tracked copilot-track.py call, covering interactive (TUI) use too.

    Unlike Claude Code's append-only per-request transcript, a Copilot session
    produces exactly one useful event (session.shutdown, written once when the
    session ends) — so the read cursor here is "has this session_id been
    processed" (copilot_read_sessions), not a byte offset. A session with no
    shutdown event yet (still running, or crashed) is simply skipped until a
    future read finds it."""

    def __init__(self, store: SqliteUsageStore, session_state_dir: Path | None = None) -> None:
        self._store = store
        env_path = os.environ.get("COPILOT_SESSION_STATE_DIR")
        self._session_state_dir = session_state_dir or (Path(env_path) if env_path else DEFAULT_SESSION_STATE_DIR)

    def read_new_events(self) -> list[CopilotUsageEvent]:
        events: list[CopilotUsageEvent] = []
        if not self._session_state_dir.is_dir():
            return events

        for session_dir in sorted(self._session_state_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            session_id = session_dir.name
            if self._store.is_copilot_session_read(session_id):
                continue

            transcript_path = session_dir / "events.jsonl"
            if not transcript_path.is_file():
                continue

            event = self._parse_session(session_id, transcript_path)
            if event is not None:
                events.append(event)
                self._store.mark_copilot_session_read(session_id)

        return events

    @staticmethod
    def _parse_session(session_id: str, path: Path) -> CopilotUsageEvent | None:
        cwd: str | None = None
        start_time: str | None = None
        shutdown_data: dict | None = None

        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"skipping malformed copilot transcript line: {exc}", file=sys.stderr)
                    continue

                record_type = record.get("type")
                if record_type == "session.start":
                    data = record.get("data") or {}
                    cwd = (data.get("context") or {}).get("cwd")
                    start_time = data.get("startTime")
                elif record_type == "session.shutdown":
                    shutdown_data = record.get("data") or {}

        if shutdown_data is None:
            return None  # session still running or crashed before shutdown

        model_metrics = shutdown_data.get("modelMetrics") or {}
        input_tokens = output_tokens = cache_read_tokens = cache_creation_tokens = 0
        for metrics in model_metrics.values():
            usage = metrics.get("usage") or {}
            input_tokens += usage.get("inputTokens", 0)
            output_tokens += usage.get("outputTokens", 0)
            cache_read_tokens += usage.get("cacheReadTokens", 0)
            cache_creation_tokens += usage.get("cacheWriteTokens", 0)

        return CopilotUsageEvent(
            timestamp=start_time or "",
            session_id=session_id,
            cwd=cwd,
            model=shutdown_data.get("currentModel", "unknown"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
