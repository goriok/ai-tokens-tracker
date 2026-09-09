from __future__ import annotations

from core.interfaces import UsageStore
from core.model import UsageEvent, usage_event_from_claude_code, usage_event_from_copilot, usage_event_from_task_call


def collect_usage_events(store: UsageStore) -> list[UsageEvent]:
    """Every tracked token event, from every source the store has, normalized
    to UsageEvent. Add a new source here (not in callers) as new adapters gain
    real per-call token data — callers stay source-agnostic."""
    events = [usage_event_from_claude_code(e) for e in store.list_claude_code_events()]
    events += [usage_event_from_task_call(c) for c in store.list_task_calls()]
    events += [usage_event_from_copilot(e) for e in store.list_copilot_events()]
    events.sort(key=lambda e: e.timestamp)
    return events


def build_dashboard_payload(store: UsageStore, since: str | None = None, until: str | None = None) -> dict:
    """JSON-serializable snapshot of everything the dashboard needs: token
    events (source-agnostic) plus agy's raw quota snapshots (kept separate —
    they're a fraction-remaining metric, not a token count, so can't be
    folded into UsageEvent without losing meaning).

    since/until (ISO-8601 strings, compared lexicographically like the
    frontend already does) filter server-side before serializing — the full
    history is tens of thousands of events (~8MB JSON as of this writing),
    most of it irrelevant to any one comparison. Filtering here, not just in
    the browser after download, is what actually cuts payload size and
    render cost; the browser-side range picker still works the same for
    events within the window. session_titles is left unfiltered — it's a
    small, cheap list (a title per session, not per event), and the range
    picker legitimately wants to offer a title even for a session whose
    events fell outside the current window."""
    events = collect_usage_events(store)
    if since is not None:
        events = [e for e in events if e.timestamp >= since]
    if until is not None:
        events = [e for e in events if e.timestamp <= until]

    snapshots = store.list_snapshots()
    if since is not None:
        snapshots = [s for s in snapshots if s.timestamp >= since]
    if until is not None:
        snapshots = [s for s in snapshots if s.timestamp <= until]

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
                "cache_creation_measured": e.cache_creation_measured,
                "total_tokens": e.total_tokens,
                "label": e.label,
                "experiment_id": e.experiment_id,
                "question_id": e.question_id,
                "strategy": e.strategy,
                "confidence_score": e.confidence_score,
            }
            for e in events
        ],
        "snapshots": [
            {
                "timestamp": s.timestamp,
                "model_group": s.model_group,
                "remaining_fraction": s.remaining_fraction,
                "reset_time": s.reset_time,
            }
            for s in snapshots
        ],
        "session_titles": [
            {"session_id": t.session_id, "title": t.title} for t in store.list_session_titles()
        ],
    }
