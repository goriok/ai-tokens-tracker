from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UsageSnapshot:
    """A zero-cost /usage poll — weekly quota remaining for one model group."""

    timestamp: str
    model_group: str
    remaining_fraction: float
    reset_time: str | None


@dataclass
class TaskCall:
    """One tracked -p call with real token usage."""

    timestamp: str
    model: str
    status: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    total_tokens: int
    duration_s: float
    task: str


@dataclass
class AgyRunResult:
    """Raw result of invoking the agy CLI in print mode."""

    status: str
    response: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    total_tokens: int


@dataclass
class ClaudeCodeUsageEvent:
    """One deduplicated request from a Claude Code transcript (.jsonl line, type=assistant)."""

    timestamp: str
    session_id: str
    project_slug: str
    cwd: str | None
    git_branch: str | None
    model: str
    request_id: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    agent_id: str | None = None


@dataclass
class SessionTitle:
    """A session's custom title (`claude -n <name>`), keyed by session_id — lets
    the dashboard filter/label runs by name instead of raw timestamps."""

    session_id: str
    title: str


@dataclass
class UsageEvent:
    """One tool-agnostic unit of token usage, normalized from any source
    adapter (Claude Code transcripts, agy tracked calls, future tools). Views
    and reports depend only on this — never on a specific tool's raw shape."""

    source: str
    timestamp: str
    model: str
    session_id: str | None
    project: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    agent_id: str | None = None
    label: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens


def usage_event_from_claude_code(event: ClaudeCodeUsageEvent) -> UsageEvent:
    return UsageEvent(
        source="claude-code",
        timestamp=event.timestamp,
        model=event.model,
        session_id=event.session_id,
        project=event.project_slug,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        cache_read_tokens=event.cache_read_input_tokens,
        cache_creation_tokens=event.cache_creation_input_tokens,
        agent_id=event.agent_id,
    )


def usage_event_from_task_call(call: TaskCall) -> UsageEvent:
    return UsageEvent(
        source="agy",
        timestamp=call.timestamp,
        model=call.model,
        session_id=None,
        project=None,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        label=call.task or None,
    )
