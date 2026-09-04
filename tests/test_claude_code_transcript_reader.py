import json

from adapters.claude_code_transcript_reader import ClaudeCodeTranscriptReader
from adapters.sqlite_usage_store import SqliteUsageStore


def _assistant_line(**overrides):
    record = {
        "type": "assistant",
        "timestamp": "2026-09-04T20:00:00Z",
        "sessionId": "sess-1",
        "requestId": "req-1",
        "cwd": "/home/user/proj",
        "gitBranch": "main",
        "message": {
            "model": "claude-sonnet-5",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 1,
                "cache_creation_input_tokens": 2,
            },
        },
    }
    record.update(overrides)
    return json.dumps(record) + "\n"


def test_read_new_events_extracts_agent_id_for_sidechain_events(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "proj-a"
    project_dir.mkdir(parents=True)
    (project_dir / "sess-1.jsonl").write_text(
        _assistant_line(isSidechain=True, agentId="agent-abc", requestId="req-1")
    )

    reader = ClaudeCodeTranscriptReader(store, projects_dir=projects_dir)
    events = reader.read_new_events()

    assert len(events) == 1
    assert events[0].agent_id == "agent-abc"
    assert events[0].session_id == "sess-1"
    store.close()


def test_read_new_events_agent_id_none_for_regular_session_events(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "proj-a"
    project_dir.mkdir(parents=True)
    (project_dir / "sess-1.jsonl").write_text(_assistant_line(requestId="req-2"))

    reader = ClaudeCodeTranscriptReader(store, projects_dir=projects_dir)
    events = reader.read_new_events()

    assert len(events) == 1
    assert events[0].agent_id is None
    store.close()


def test_read_new_events_recurses_into_subagents_directory(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "proj-a"
    subagents_dir = project_dir / "subagents" / "workflows" / "wf_1"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-xyz.jsonl").write_text(
        _assistant_line(isSidechain=True, agentId="agent-xyz", requestId="req-3")
    )

    reader = ClaudeCodeTranscriptReader(store, projects_dir=projects_dir)
    events = reader.read_new_events()

    assert len(events) == 1
    assert events[0].agent_id == "agent-xyz"
    store.close()


def test_read_new_events_records_custom_title_for_session(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "proj-a"
    project_dir.mkdir(parents=True)
    lines = (
        json.dumps({"type": "custom-title", "customTitle": "A1", "sessionId": "sess-1"}) + "\n"
        + _assistant_line(requestId="req-4")
    )
    (project_dir / "sess-1.jsonl").write_text(lines)

    reader = ClaudeCodeTranscriptReader(store, projects_dir=projects_dir)
    reader.read_new_events()

    titles = store.list_session_titles()
    assert len(titles) == 1
    assert titles[0].session_id == "sess-1"
    assert titles[0].title == "A1"
    store.close()
