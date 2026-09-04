from core.model import ClaudeCodeUsageEvent, TaskCall, usage_event_from_claude_code, usage_event_from_task_call


def test_usage_event_from_claude_code_normalizes_fields():
    event = ClaudeCodeUsageEvent(
        timestamp="2026-09-01T10:00:00Z",
        session_id="sess-1",
        project_slug="my-project",
        cwd="/home/user/my-project",
        git_branch="main",
        model="claude-sonnet-5",
        request_id="req-1",
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=30,
        cache_creation_input_tokens=20,
    )

    result = usage_event_from_claude_code(event)

    assert result.source == "claude-code"
    assert result.timestamp == "2026-09-01T10:00:00Z"
    assert result.model == "claude-sonnet-5"
    assert result.session_id == "sess-1"
    assert result.project == "my-project"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.cache_read_tokens == 30
    assert result.cache_creation_tokens == 20
    assert result.total_tokens == 200
    assert result.agent_id is None


def test_usage_event_from_claude_code_propagates_agent_id_for_sidechain_events():
    event = ClaudeCodeUsageEvent(
        timestamp="2026-09-01T10:00:00Z",
        session_id="sess-1",
        project_slug="my-project",
        cwd="/home/user/my-project",
        git_branch="main",
        model="claude-sonnet-5",
        request_id="req-1",
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=30,
        cache_creation_input_tokens=20,
        agent_id="agent-abc",
    )

    result = usage_event_from_claude_code(event)

    assert result.agent_id == "agent-abc"


def test_usage_event_from_task_call_normalizes_fields():
    call = TaskCall(
        timestamp="2026-09-02T08:00:00Z",
        model="gemini-3.7-flash-low",
        status="SUCCESS",
        input_tokens=400,
        output_tokens=100,
        thinking_tokens=25,
        total_tokens=500,
        duration_s=3.2,
        task="revisão de PR",
    )

    result = usage_event_from_task_call(call)

    assert result.source == "agy"
    assert result.timestamp == "2026-09-02T08:00:00Z"
    assert result.model == "gemini-3.7-flash-low"
    assert result.session_id is None
    assert result.project is None
    assert result.input_tokens == 400
    assert result.output_tokens == 100
    assert result.cache_read_tokens == 0
    assert result.cache_creation_tokens == 0
    assert result.total_tokens == 500
