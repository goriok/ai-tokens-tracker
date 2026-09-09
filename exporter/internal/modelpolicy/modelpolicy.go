// Package modelpolicy is a Go port of the removed Python
// core/model_policy.py — task complexity + remaining quota -> concrete agy
// model. Pure domain logic, no I/O: callers fetch the quota snapshots
// (agycli.Runner.FetchQuota) and pass them in.
//
// Best-effort mapping against the models `agy models` listed at the time
// this was written — if agy adds/removes models, this may need an update
// (no attempt to query the model list dynamically; that's a bigger surface
// than this needs — same trade-off the removed Python made).
package modelpolicy

import (
	"fmt"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

type complexityModels struct {
	gemini string // used when Gemini quota is healthy
	other  string // used when Gemini quota is running low
}

var complexityToModel = map[string]complexityModels{
	"low":    {"gemini-3.8-flash-low", "gpt-oss-120b-medium"},
	"medium": {"gemini-3.8-flash-medium", "claude-sonnet-4-6"},
	"high":   {"gemini-3.1-pro-high", "claude-opus-4-6-thinking"},
}

const (
	geminiGroup       = "Gemini Models"
	lowQuotaThreshold = 0.15 // below this remaining fraction, avoid that group
)

// ChooseModel picks a model for the given task complexity ("low"/"medium"/
// "high"), steering away from a model group whose weekly quota is running
// low. snapshots is assumed ordered by timestamp, oldest first — the last
// Gemini Models snapshot in it is what decides (mirrors the removed
// Python's gemini_snapshots[-1]).
func ChooseModel(complexity string, snapshots []model.UsageSnapshot) (string, error) {
	models, ok := complexityToModel[complexity]
	if !ok {
		return "", fmt.Errorf("unknown complexity %q — expected low/medium/high", complexity)
	}

	var latestGemini *model.UsageSnapshot
	for i := range snapshots {
		if snapshots[i].ModelGroup == geminiGroup {
			latestGemini = &snapshots[i]
		}
	}

	if latestGemini == nil {
		return models.gemini, nil // no quota data yet — default to the cheaper option
	}
	if latestGemini.RemainingFraction < lowQuotaThreshold {
		return models.other, nil
	}
	return models.gemini, nil
}
