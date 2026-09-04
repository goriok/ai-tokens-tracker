from core.model import ClaudeCodeUsageEvent, TaskCall, UsageSnapshot
from core.usage import build_dashboard_payload, collect_usage_events


class FakeUsageStore:
    def __init__(self, claude_code_events=(), task_calls=(), snapshots=()):
        self._claude_code_events = list(claude_code_events)
        self._task_calls = list(task_calls)
        self._snapshots = list(snapshots)

    def list_claude_code_events(self):
        return self._claude_code_events

    def list_task_calls(self):
        return self._task_calls

    def list_snapshots(self):
        return self._snapshots


def _cc_event(timestamp, request_id="req-1"):
    return ClaudeCodeUsageEvent(
        timestamp=timestamp,
        session_id="sess-1",
        project_slug="proj-a",
        cwd=None,
        git_branch=None,
        model="claude-sonnet-5",
        request_id=request_id,
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def _task_call(timestamp):
    return TaskCall(
        timestamp=timestamp,
        model="gemini-3.7-flash-low",
        status="SUCCESS",
        input_tokens=20,
        output_tokens=10,
        thinking_tokens=0,
        total_tokens=30,
        duration_s=1.0,
        task="",
    )


def test_collect_usage_events_merges_and_sorts_across_sources():
    store = FakeUsageStore(
        claude_code_events=[_cc_event("2026-09-01T12:00:00Z")],
        task_calls=[_task_call("2026-09-01T08:00:00Z")],
    )

    events = collect_usage_events(store)

    assert [e.source for e in events] == ["agy", "claude-code"]
    assert [e.timestamp for e in events] == ["2026-09-01T08:00:00Z", "2026-09-01T12:00:00Z"]


def test_collect_usage_events_empty_store_returns_empty_list():
    store = FakeUsageStore()

    events = collect_usage_events(store)

    assert events == []


def test_build_dashboard_payload_serializes_events_and_snapshots():
    store = FakeUsageStore(
        claude_code_events=[_cc_event("2026-09-01T12:00:00Z")],
        task_calls=[_task_call("2026-09-01T08:00:00Z")],
        snapshots=[
            UsageSnapshot(
                timestamp="2026-09-01T09:00:00Z",
                model_group="gemini-3.7",
                remaining_fraction=0.8,
                reset_time="2026-09-07T00:00:00Z",
            )
        ],
    )

    payload = build_dashboard_payload(store)

    assert [e["source"] for e in payload["events"]] == ["agy", "claude-code"]
    assert payload["events"][0]["total_tokens"] == 30
    assert payload["snapshots"] == [
        {
            "timestamp": "2026-09-01T09:00:00Z",
            "model_group": "gemini-3.7",
            "remaining_fraction": 0.8,
            "reset_time": "2026-09-07T00:00:00Z",
        }
    ]


def test_build_dashboard_payload_empty_store():
    store = FakeUsageStore()

    payload = build_dashboard_payload(store)

    assert payload == {"events": [], "snapshots": []}
