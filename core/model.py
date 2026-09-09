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
    cache_read_tokens: int = 0
    source: str = "agy"
    cache_creation_tokens: int = 0
    confidence_score: float | None = None
    """Filled in later via an update, after the confidence-analysis
    validation runs (not known at record_task_call time)."""


@dataclass
class AgyRunResult:
    """Raw result of invoking a CLI in print mode with real token usage
    (agy, or another source shaped the same way — e.g. Copilot CLI)."""

    status: str
    response: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    total_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    resolved_model: str | None = None
    """The model the CLI actually used, when it can differ from the one
    requested (e.g. Copilot's --model auto). None when the caller's
    requested model is always the one that ran (agy)."""


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
class CopilotUsageEvent:
    """One Copilot CLI session's token usage, from the session.shutdown event
    in ~/.copilot/session-state/<session_id>/events.jsonl — the automatic,
    zero-cost counterpart to a copilot-track.py call. Deduplicated by
    session_id (one shutdown event per session, unlike Claude Code's
    per-request request_id)."""

    timestamp: str
    session_id: str
    cwd: str | None
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


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
    cache_creation_measured: bool = True
    """False when the source CLI doesn't report cache-write/creation tokens
    at all (agy, as of this writing) — cache_creation_tokens is then 0
    because it's unmeasured, not because it's confirmed zero. Keeping this
    explicit stops agy from silently reading as cheaper than sources (Claude
    Code, Copilot) that do report this cost."""
    confidence_score: float | None = None
    """From copilot/agy TaskCalls that recorded it. None for claude-code and
    for any event with no confidence-analysis score."""

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


def usage_event_from_copilot(event: CopilotUsageEvent) -> UsageEvent:
    return UsageEvent(
        source="copilot",
        timestamp=event.timestamp,
        model=event.model,
        session_id=event.session_id,
        project=event.cwd,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        cache_read_tokens=event.cache_read_tokens,
        cache_creation_tokens=event.cache_creation_tokens,
    )


def usage_event_from_task_call(call: TaskCall) -> UsageEvent:
    return UsageEvent(
        source=call.source,
        timestamp=call.timestamp,
        model=call.model,
        session_id=None,
        project=None,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cache_read_tokens=call.cache_read_tokens,
        cache_creation_tokens=call.cache_creation_tokens,
        label=call.task or None,
        # agy's CLI output has no cache-write field — 0 is "unmeasured".
        # Copilot and Claude Code both report this genuinely.
        cache_creation_measured=call.source != "agy",
        confidence_score=call.confidence_score,
    )
