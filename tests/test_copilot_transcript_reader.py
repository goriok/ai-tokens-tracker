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


def _write_session(sessions_dir, session_id, lines):
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "events.jsonl").write_text("".join(lines))


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
