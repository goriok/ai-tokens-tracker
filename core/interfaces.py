from __future__ import annotations

from typing import Protocol

from core.model import AgyRunResult, ClaudeCodeUsageEvent, TaskCall, UsageSnapshot


class UsageStore(Protocol):
    """Secondary/driven port for persisting usage data."""

    def record_snapshot(self, snapshot: UsageSnapshot) -> None: ...

    def record_task_call(self, call: TaskCall) -> None: ...

    def list_snapshots(self) -> list[UsageSnapshot]: ...

    def list_task_calls(self) -> list[TaskCall]: ...


class AgyRunner(Protocol):
    """Secondary/driven port for invoking the agy CLI."""

    def fetch_usage(self) -> list[UsageSnapshot]:
        """Zero-cost /usage poll — one snapshot per model group."""
        ...

    def run_task(self, prompt: str, *, model: str, effort: str | None = None, skip_permissions: bool = False) -> AgyRunResult: ...


class ClaudeCodeTranscriptReader(Protocol):
    """Secondary/driven port for reading Claude Code session transcripts."""

    def read_new_events(self) -> list[ClaudeCodeUsageEvent]:
        """Every not-yet-seen assistant request across all transcripts, deduplicated by request_id."""
        ...
