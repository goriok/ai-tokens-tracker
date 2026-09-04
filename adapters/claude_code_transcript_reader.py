from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from adapters.sqlite_usage_store import SqliteUsageStore
from core.model import ClaudeCodeUsageEvent

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"


class ClaudeCodeTranscriptReader:
    """ClaudeCodeTranscriptReader adapter backed by local .jsonl session transcripts."""

    def __init__(self, store: SqliteUsageStore, projects_dir: Path | None = None) -> None:
        self._store = store
        env_path = os.environ.get("CLAUDE_CODE_PROJECTS_DIR")
        self._projects_dir = projects_dir or (Path(env_path) if env_path else DEFAULT_PROJECTS_DIR)

    def read_new_events(self) -> list[ClaudeCodeUsageEvent]:
        events: list[ClaudeCodeUsageEvent] = []
        if not self._projects_dir.is_dir():
            return events

        for project_dir in sorted(self._projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            for transcript_path in sorted(project_dir.glob("*.jsonl")):
                events.extend(self._read_new_events_from_file(project_dir.name, transcript_path))
        return events

    def _read_new_events_from_file(self, project_slug: str, path: Path) -> list[ClaudeCodeUsageEvent]:
        key = str(path)
        offset = self._store.get_claude_code_cursor(key)
        events: list[ClaudeCodeUsageEvent] = []
        seen_request_ids: set[str] = set()

        with path.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            for line in fh:
                event = self._parse_line(project_slug, line, seen_request_ids)
                if event is not None:
                    events.append(event)
            new_offset = fh.tell()

        self._store.set_claude_code_cursor(key, new_offset)
        return events

    @staticmethod
    def _parse_line(project_slug: str, line: str, seen_request_ids: set[str]) -> ClaudeCodeUsageEvent | None:
        line = line.strip()
        if not line:
            return None
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"skipping malformed transcript line: {exc}", file=sys.stderr)
            return None

        if record.get("type") != "assistant":
            return None

        message = record.get("message") or {}
        usage = message.get("usage")
        if not usage:
            return None

        request_id = record.get("requestId")
        if not request_id or request_id in seen_request_ids:
            return None
        seen_request_ids.add(request_id)

        return ClaudeCodeUsageEvent(
            timestamp=record.get("timestamp", ""),
            session_id=record.get("sessionId", ""),
            project_slug=project_slug,
            cwd=record.get("cwd"),
            git_branch=record.get("gitBranch"),
            model=message.get("model", "unknown"),
            request_id=request_id,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        )
