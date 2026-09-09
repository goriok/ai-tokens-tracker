import pytest

from adapters.sqlite_usage_store import SqliteUsageStore
from core.model import ClaudeCodeUsageEvent, SessionTitle, TaskCall


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


def test_record_and_list_session_title_roundtrips(store):
    store.record_session_title(SessionTitle(session_id="sess-1", title="A1"))

    titles = store.list_session_titles()

    assert len(titles) == 1
    assert titles[0].session_id == "sess-1"
    assert titles[0].title == "A1"


def test_record_session_title_upserts_on_same_session_id(store):
    store.record_session_title(SessionTitle(session_id="sess-1", title="old-name"))
    store.record_session_title(SessionTitle(session_id="sess-1", title="new-name"))

    titles = store.list_session_titles()

    assert len(titles) == 1
    assert titles[0].title == "new-name"


def test_record_and_list_task_call_roundtrips_cache_read_tokens(store):
    store.record_task_call(
        TaskCall(
            timestamp="2026-09-04T21:27:52Z",
            model="gemini-3.8-flash-medium",
            status="SUCCESS",
            input_tokens=33636,
            output_tokens=758,
            thinking_tokens=200,
            total_tokens=34394,
            duration_s=11.1,
            task="A1",
            cache_read_tokens=8108,
        )
    )

    calls = store.list_task_calls()

    assert len(calls) == 1
    assert calls[0].task == "A1"
    assert calls[0].cache_read_tokens == 8108


def test_record_and_list_task_call_roundtrips_source(store):
    store.record_task_call(
        TaskCall(
            timestamp="2026-09-09T14:30:00Z",
            model="mai-code-1.1-flash",
            status="SUCCESS",
            input_tokens=8140,
            output_tokens=12,
            thinking_tokens=0,
            total_tokens=8152,
            duration_s=3.0,
            task="B1",
            source="copilot",
        )
    )

    calls = store.list_task_calls()

    assert len(calls) == 1
    assert calls[0].source == "copilot"


def test_task_call_source_defaults_to_agy(store):
    store.record_task_call(
        TaskCall(
            timestamp="2026-09-04T21:27:52Z",
            model="gemini-3.8-flash-medium",
            status="SUCCESS",
            input_tokens=100,
            output_tokens=50,
            thinking_tokens=0,
            total_tokens=150,
            duration_s=1.0,
            task="A1",
        )
    )

    calls = store.list_task_calls()

    assert calls[0].source == "agy"


def test_record_and_list_task_call_roundtrips_experiment_fields(store):
    store.record_task_call(
        TaskCall(
            timestamp="2026-09-09T14:30:00Z",
            model="mai-code-1.1-flash",
            status="SUCCESS",
            input_tokens=100,
            output_tokens=10,
            thinking_tokens=0,
            total_tokens=110,
            duration_s=3.0,
            task="rag-vs-manual-single-call|q1|codigo-direto",
            experiment_id="rag-vs-manual-single-call",
            question_id="q1",
            strategy="codigo-direto",
        )
    )

    calls = store.list_task_calls()

    assert calls[0].experiment_id == "rag-vs-manual-single-call"
    assert calls[0].question_id == "q1"
    assert calls[0].strategy == "codigo-direto"
    assert calls[0].confidence_score is None


def test_task_call_experiment_fields_default_to_none(store):
    store.record_task_call(
        TaskCall(
            timestamp="2026-09-04T21:27:52Z",
            model="gemini-3.8-flash-medium",
            status="SUCCESS",
            input_tokens=100,
            output_tokens=50,
            thinking_tokens=0,
            total_tokens=150,
            duration_s=1.0,
            task="A1",
        )
    )

    calls = store.list_task_calls()

    assert calls[0].experiment_id is None
    assert calls[0].question_id is None
    assert calls[0].strategy is None
    assert calls[0].confidence_score is None


def test_update_task_call_confidence_score_sets_score_without_touching_other_fields(store):
    store.record_task_call(
        TaskCall(
            timestamp="2026-09-09T14:30:00Z",
            model="mai-code-1.1-flash",
            status="SUCCESS",
            input_tokens=100,
            output_tokens=10,
            thinking_tokens=0,
            total_tokens=110,
            duration_s=3.0,
            task="B1",
        )
    )

    store.update_task_call_confidence_score("B1", 7.5)

    calls = store.list_task_calls()
    assert calls[0].confidence_score == 7.5
    assert calls[0].input_tokens == 100
