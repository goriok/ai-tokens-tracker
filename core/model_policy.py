"""Model selection policy: task complexity + remaining quota -> concrete agy model.

Best-effort mapping against the models `agy models` listed at the time this was
written — if agy adds/removes models, this may need an update (no attempt to
query the model list dynamically; that's a bigger surface than this needs).
"""
from __future__ import annotations

from core.model import UsageSnapshot

# (complexity -> (gemini model when Gemini quota is healthy, 3p model when Gemini quota is low))
_COMPLEXITY_TO_MODEL = {
    "low": ("gemini-3.8-flash-low", "gpt-oss-120b-medium"),
    "medium": ("gemini-3.8-flash-medium", "claude-sonnet-4-6"),
    "high": ("gemini-3.1-pro-high", "claude-opus-4-6-thinking"),
}

_GEMINI_GROUP = "Gemini Models"
_LOW_QUOTA_THRESHOLD = 0.15  # below this remaining fraction, avoid that group


def choose_model(complexity: str, snapshots: list[UsageSnapshot]) -> str:
    """Pick a model for the given task complexity ("low"/"medium"/"high"), steering
    away from a model group whose weekly quota is running low."""
    if complexity not in _COMPLEXITY_TO_MODEL:
        raise ValueError(f"unknown complexity '{complexity}' — expected low/medium/high")

    gemini_model, other_model = _COMPLEXITY_TO_MODEL[complexity]

    gemini_snapshots = [s for s in snapshots if s.model_group == _GEMINI_GROUP]
    if not gemini_snapshots:
        # No quota data yet — default to Gemini, the cheaper option.
        return gemini_model

    latest_gemini = gemini_snapshots[-1]  # snapshots ordered by timestamp
    if latest_gemini.remaining_fraction < _LOW_QUOTA_THRESHOLD:
        return other_model
    return gemini_model
