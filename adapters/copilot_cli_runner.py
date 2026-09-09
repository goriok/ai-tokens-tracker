from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from core.model import AgyRunResult


class CopilotCliRunner:
    """AgyRunner-shaped adapter backed by the real `copilot` binary via subprocess.

    Copilot writes clean per-call usage as JSON via --usage-output-file, unlike
    agy's --output-format json (usage embedded in stdout) — so this runner reads
    that file instead of parsing stdout for token counts. --disable-builtin-mcps
    drops the unused GitHub MCP tools (~9.4k tokens of fixed schema overhead per
    call, confirmed by measurement), --allow-all-tools is required in
    non-interactive mode."""

    def __init__(self, binary: str = "copilot") -> None:
        self._binary = binary

    def run_task(self, prompt: str, *, model: str = "auto") -> AgyRunResult:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            usage_path = Path(tmp.name)
        try:
            cmd = [
                self._binary,
                "-p",
                prompt,
                "--model",
                model,
                "--allow-all-tools",
                "--disable-builtin-mcps",
                "--usage-output-file",
                str(usage_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            usage = json.loads(usage_path.read_text())
            token_details = usage.get("tokenDetails", {})
            # Copilot's "input" field is the fresh (non-cached) portion only —
            # cache_write (new context added to the prompt cache this call) is
            # reported separately and can dwarf "input" on a cache-cold call
            # (confirmed: a trivial prompt showed input=3, cache_write=16522).
            # Mirrors Claude Code's input_tokens vs cache_creation_input_tokens
            # split, so it maps the same way onto UsageEvent.
            input_tokens = token_details.get("input", {}).get("tokenCount", 0)
            output_tokens = token_details.get("output", {}).get("tokenCount", 0)
            cache_read_tokens = token_details.get("cache_read", {}).get("tokenCount", 0)
            cache_creation_tokens = token_details.get("cache_write", {}).get("tokenCount", 0)
            return AgyRunResult(
                status="SUCCESS" if result.returncode == 0 else "ERROR",
                response=result.stdout,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thinking_tokens=0,
                total_tokens=input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                resolved_model=usage.get("currentModel"),
            )
        finally:
            usage_path.unlink(missing_ok=True)
