import json

from adapters.copilot_transcript_reader import CopilotTranscriptReader
from adapters.sqlite_usage_store import SqliteUsageStore


def _session_start(session_id="sess-1", cwd="/home/user/proj", start_time="2026-09-09T12:00:00.000Z"):
    return json.dumps({
        "type": "session.start",
        "data": {"sessionId": session_id, "startTime": start_time, "context": {"cwd": cwd}},
    }) + "\n"


def _session_shutdown(model="mai-code-1.1-flash", input_tokens=100, output_tokens=10,
                       cache_read=5, cache_write=2):
    return json.dumps({
        "type": "session.shutdown",
        "data": {
            "currentModel": model,
            "modelMetrics": {
                model: {
                    "usage": {
                        "inputTokens": input_tokens,
                        "outputTokens": output_tokens,
                        "cacheReadTokens": cache_read,
                        "cacheWriteTokens": cache_write,
                    },
                },
            },
        },
    }) + "\n"


def _write_session(sessions_dir, session_id, lines, workspace_yaml=None):
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "events.jsonl").write_text("".join(lines))
    if workspace_yaml is not None:
        (session_dir / "workspace.yaml").write_text(workspace_yaml)


def test_read_new_events_extracts_token_usage(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    sessions_dir = tmp_path / "session-state"
    _write_session(sessions_dir, "sess-1", [
        _session_start(session_id="sess-1", cwd="/home/user/proj"),
        _session_shutdown(),
    ])

    reader = CopilotTranscriptReader(store, session_state_dir=sessions_dir)
    events = reader.read_new_events()

    assert len(events) == 1
    assert events[0].session_id == "sess-1"
    assert events[0].cwd == "/home/user/proj"
    assert events[0].model == "mai-code-1.1-flash"
    assert events[0].input_tokens == 100
    assert events[0].output_tokens == 10
    assert events[0].cache_read_tokens == 5
    assert events[0].cache_creation_tokens == 2
    store.close()


def test_read_new_events_skips_session_without_shutdown(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    sessions_dir = tmp_path / "session-state"
    _write_session(sessions_dir, "sess-1", [_session_start(session_id="sess-1")])

    reader = CopilotTranscriptReader(store, session_state_dir=sessions_dir)
    events = reader.read_new_events()

    assert events == []
    store.close()


def test_read_new_events_skips_already_read_sessions(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    sessions_dir = tmp_path / "session-state"
    _write_session(sessions_dir, "sess-1", [_session_start(session_id="sess-1"), _session_shutdown()])

    reader = CopilotTranscriptReader(store, session_state_dir=sessions_dir)
    first = reader.read_new_events()
    second = reader.read_new_events()

    assert len(first) == 1
    assert second == []
    store.close()


def test_read_new_events_sums_tokens_across_multiple_models(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    sessions_dir = tmp_path / "session-state"
    shutdown = json.dumps({
        "type": "session.shutdown",
        "data": {
            "currentModel": "model-b",
            "modelMetrics": {
                "model-a": {"usage": {"inputTokens": 100, "outputTokens": 10, "cacheReadTokens": 0, "cacheWriteTokens": 0}},
                "model-b": {"usage": {"inputTokens": 50, "outputTokens": 5, "cacheReadTokens": 0, "cacheWriteTokens": 0}},
            },
        },
    }) + "\n"
    _write_session(sessions_dir, "sess-1", [_session_start(session_id="sess-1"), shutdown])

    reader = CopilotTranscriptReader(store, session_state_dir=sessions_dir)
    events = reader.read_new_events()

    assert len(events) == 1
    assert events[0].input_tokens == 150
    assert events[0].output_tokens == 15
    assert events[0].model == "model-b"
    store.close()


def test_read_new_events_records_session_title_from_workspace_yaml(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    sessions_dir = tmp_path / "session-state"
    _write_session(
        sessions_dir, "sess-1",
        [_session_start(session_id="sess-1"), _session_shutdown()],
        workspace_yaml="id: sess-1\nname: 'quanto é 5+5?'\nuser_named: false\n",
    )

    reader = CopilotTranscriptReader(store, session_state_dir=sessions_dir)
    reader.read_new_events()

    titles = store.list_session_titles()
    assert len(titles) == 1
    assert titles[0].session_id == "sess-1"
    assert titles[0].title == "quanto é 5+5?"
    store.close()


def test_read_new_events_ignores_missing_or_blank_workspace_yaml_name(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    sessions_dir = tmp_path / "session-state"
    _write_session(sessions_dir, "sess-1", [_session_start(session_id="sess-1"), _session_shutdown()])
    _write_session(
        sessions_dir, "sess-2",
        [_session_start(session_id="sess-2"), _session_shutdown()],
        workspace_yaml="id: sess-2\nname: ''\nuser_named: false\n",
    )

    reader = CopilotTranscriptReader(store, session_state_dir=sessions_dir)
    reader.read_new_events()

    assert store.list_session_titles() == []
    store.close()


def test_read_new_events_records_title_even_for_session_without_shutdown(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    sessions_dir = tmp_path / "session-state"
    _write_session(
        sessions_dir, "sess-1",
        [_session_start(session_id="sess-1")],
        workspace_yaml="id: sess-1\nname: still running\nuser_named: false\n",
    )

    reader = CopilotTranscriptReader(store, session_state_dir=sessions_dir)
    events = reader.read_new_events()

    assert events == []
    titles = store.list_session_titles()
    assert len(titles) == 1
    assert titles[0].title == "still running"
    store.close()


def test_read_new_events_records_title_even_for_already_read_session(tmp_path):
    store = SqliteUsageStore(db_path=tmp_path / "usage.db")
    sessions_dir = tmp_path / "session-state"
    _write_session(
        sessions_dir, "sess-1",
        [_session_start(session_id="sess-1"), _session_shutdown()],
        workspace_yaml="id: sess-1\nname: first name\nuser_named: false\n",
    )
    reader = CopilotTranscriptReader(store, session_state_dir=sessions_dir)
    reader.read_new_events()

    (sessions_dir / "sess-1" / "workspace.yaml").write_text("id: sess-1\nname: renamed\nuser_named: true\n")
    reader.read_new_events()

    titles = store.list_session_titles()
    assert len(titles) == 1
    assert titles[0].title == "renamed"
    store.close()
