from __future__ import annotations

from core.interfaces import UsageStore
from core.model import UsageEvent, usage_event_from_claude_code, usage_event_from_task_call


def collect_usage_events(store: UsageStore) -> list[UsageEvent]:
    """Every tracked token event, from every source the store has, normalized
    to UsageEvent. Add a new source here (not in callers) as new adapters gain
    real per-call token data — callers stay source-agnostic."""
    events = [usage_event_from_claude_code(e) for e in store.list_claude_code_events()]
    events += [usage_event_from_task_call(c) for c in store.list_task_calls()]
    events.sort(key=lambda e: e.timestamp)
    return events


def build_dashboard_payload(store: UsageStore) -> dict:
    """JSON-serializable snapshot of everything the dashboard needs: token
    events (source-agnostic) plus agy's raw quota snapshots (kept separate —
    they're a fraction-remaining metric, not a token count, so can't be
    folded into UsageEvent without losing meaning)."""
    return {
        "events": [
            {
                "source": e.source,
                "timestamp": e.timestamp,
                "model": e.model,
                "session_id": e.session_id,
                "project": e.project,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "cache_read_tokens": e.cache_read_tokens,
                "cache_creation_tokens": e.cache_creation_tokens,
                "total_tokens": e.total_tokens,
            }
            for e in collect_usage_events(store)
        ],
        "snapshots": [
            {
                "timestamp": s.timestamp,
                "model_group": s.model_group,
                "remaining_fraction": s.remaining_fraction,
                "reset_time": s.reset_time,
            }
            for s in store.list_snapshots()
        ],
    }
