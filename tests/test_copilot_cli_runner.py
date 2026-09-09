import json
from unittest.mock import MagicMock, patch

from adapters.copilot_cli_runner import CopilotCliRunner


def _usage_json(**overrides):
    # Shape confirmed against a real `copilot ... --usage-output-file` run.
    usage = {
        "currentModel": "mai-code-1.1-flash",
        "tokenDetails": {
            "input": {"tokenCount": 8140},
            "output": {"tokenCount": 12},
            "cache_read": {"tokenCount": 0},
            "cache_write": {"tokenCount": 0},
        },
    }
    usage.update(overrides)
    return usage


def _completed_process(stdout="the answer", returncode=0):
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    return result


def _patch_run(usage_extra=None, **process_kwargs):
    def fake_run(cmd, **kwargs):
        usage_path = cmd[cmd.index("--usage-output-file") + 1]
        with open(usage_path, "w") as f:
            json.dump(_usage_json(**(usage_extra or {})), f)
        return _completed_process(**process_kwargs)

    return patch("subprocess.run", side_effect=fake_run)


def test_run_task_maps_token_details():
    runner = CopilotCliRunner()
    with _patch_run():
        result = runner.run_task("hello", model="auto")

    assert result.input_tokens == 8140
    assert result.output_tokens == 12
    assert result.cache_read_tokens == 0
    assert result.total_tokens == 8152


def test_run_task_captures_resolved_model():
    runner = CopilotCliRunner()
    with _patch_run():
        result = runner.run_task("hello", model="auto")

    assert result.resolved_model == "mai-code-1.1-flash"


def test_run_task_status_error_on_nonzero_exit():
    runner = CopilotCliRunner()
    with _patch_run(returncode=1):
        result = runner.run_task("hello", model="auto")

    assert result.status == "ERROR"


def test_run_task_response_is_command_stdout():
    runner = CopilotCliRunner()
    with _patch_run(stdout="the final answer"):
        result = runner.run_task("hello", model="auto")

    assert result.response == "the final answer"
