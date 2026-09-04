from fastapi.testclient import TestClient

from adapters.sqlite_usage_store import SqliteUsageStore
from core.model import ClaudeCodeUsageEvent
from scripts.token_dashboard_server import create_app


def _event(request_id, timestamp="2026-09-01T10:00:00Z"):
    return ClaudeCodeUsageEvent(
        timestamp=timestamp,
        session_id="sess-1",
        project_slug="proj-a",
        cwd=None,
        git_branch=None,
        model="claude-sonnet-5",
        request_id=request_id,
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def test_api_usage_returns_events_from_store(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    store.record_claude_code_event(_event("req-1"))

    client = TestClient(create_app(store))
    response = client.get("/api/usage")

    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["source"] == "claude-code"
    assert body["snapshots"] == []


def test_index_serves_html(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    client = TestClient(create_app(store))

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
