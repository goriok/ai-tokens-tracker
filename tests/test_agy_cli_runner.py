import json
from unittest.mock import MagicMock, patch

from adapters.agy_cli_runner import AgyCliRunner


def _completed_process(usage_extra=None):
    usage = {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 5, "total_tokens": 120}
    usage.update(usage_extra or {})
    payload = {"status": "SUCCESS", "response": "ok", "usage": usage}
    result = MagicMock()
    result.stdout = json.dumps(payload)
    return result


def test_run_task_captures_cache_read_tokens():
    runner = AgyCliRunner()
    with patch("subprocess.run", return_value=_completed_process({"cache_read_tokens": 8108})):
        result = runner.run_task("hello", model="gemini-3.8-flash-medium")

    assert result.cache_read_tokens == 8108


def test_run_task_cache_read_tokens_defaults_to_zero_when_absent():
    runner = AgyCliRunner()
    with patch("subprocess.run", return_value=_completed_process()):
        result = runner.run_task("hello", model="gemini-3.8-flash-medium")

    assert result.cache_read_tokens == 0
