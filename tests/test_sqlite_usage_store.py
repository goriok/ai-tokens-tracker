import pytest

from adapters.sqlite_usage_store import SqliteUsageStore
from core.model import ClaudeCodeUsageEvent


@pytest.fixture
def store(tmp_path):
    s = SqliteUsageStore(db_path=tmp_path / "usage.db")
    yield s
    s.close()


def _event(request_id, timestamp="2026-09-01T10:00:00Z"):
    return ClaudeCodeUsageEvent(
        timestamp=timestamp,
        session_id="sess-1",
        project_slug="proj-a",
        cwd="/home/user/proj-a",
        git_branch="main",
        model="claude-sonnet-5",
        request_id=request_id,
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=10,
        cache_creation_input_tokens=5,
    )


def test_record_and_list_claude_code_event_roundtrips(store):
    store.record_claude_code_event(_event("req-1"))

    events = store.list_claude_code_events()

    assert len(events) == 1
    assert events[0].request_id == "req-1"
    assert events[0].input_tokens == 100


def test_record_claude_code_event_dedupes_by_request_id(store):
    store.record_claude_code_event(_event("req-1", timestamp="2026-09-01T10:00:00Z"))
    store.record_claude_code_event(_event("req-1", timestamp="2026-09-01T11:00:00Z"))

    events = store.list_claude_code_events()

    assert len(events) == 1
    assert events[0].timestamp == "2026-09-01T10:00:00Z"
