from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from core.model import AgyRunResult, UsageSnapshot


class AgyCliRunner:
    """AgyRunner adapter backed by the real `agy` binary via subprocess."""

    def __init__(self, binary: str = "agy") -> None:
        self._binary = binary

    def fetch_usage(self) -> list[UsageSnapshot]:
        result = subprocess.run(
            [self._binary, "-p", "/usage", "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        result.check_returncode()
        data = json.loads(result.stdout)
        groups = data.get("command", {}).get("data", {}).get("groups", [])

        now = datetime.now(timezone.utc).isoformat()
        snapshots = []
        for group in groups:
            name = group.get("name", "unknown")
            for bucket in group.get("buckets", []):
                snapshots.append(
                    UsageSnapshot(
                        timestamp=now,
                        model_group=name,
                        remaining_fraction=bucket.get("remaining_fraction", 0.0),
                        reset_time=bucket.get("reset_time"),
                    )
                )
        return snapshots

    def run_task(
        self, prompt: str, *, model: str, effort: str | None = None, skip_permissions: bool = False
    ) -> AgyRunResult:
        cmd = [self._binary, "-p", prompt, "--model", model, "--output-format", "json"]
        if effort:
            cmd += ["--effort", effort]
        if skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        data = json.loads(result.stdout)
        usage = data.get("usage", {})
        return AgyRunResult(
            status=data.get("status", "UNKNOWN"),
            response=data.get("response", ""),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            thinking_tokens=usage.get("thinking_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
