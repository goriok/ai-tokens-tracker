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
