package modelpolicy

import (
	"testing"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// TestChooseModel_PicksGeminiWhenNoQuotaDataYet is the seam: given a
// complexity level and a set of quota snapshots, ChooseModel returns the
// concrete agy model name to use — mirroring the removed Python
// core/model_policy.py's choose_model exactly (same thresholds, same
// model names, same "default to the cheaper Gemini option" behavior with
// no quota data).
func TestChooseModel_PicksGeminiWhenNoQuotaDataYet(t *testing.T) {
	got, err := ChooseModel("low", nil)
	if err != nil {
		t.Fatalf("ChooseModel: %v", err)
	}
	if got != "gemini-3.8-flash-low" {
		t.Errorf("got %q, want gemini-3.8-flash-low", got)
	}
}

func TestChooseModel_PicksGeminiWhenQuotaHealthy(t *testing.T) {
	snapshots := []model.UsageSnapshot{
		{ModelGroup: "Gemini Models", RemainingFraction: 0.5},
	}
	got, err := ChooseModel("medium", snapshots)
	if err != nil {
		t.Fatalf("ChooseModel: %v", err)
	}
	if got != "gemini-3.8-flash-medium" {
		t.Errorf("got %q, want gemini-3.8-flash-medium", got)
	}
}

func TestChooseModel_StearsAwayFromGeminiWhenQuotaLow(t *testing.T) {
	snapshots := []model.UsageSnapshot{
		{ModelGroup: "Gemini Models", RemainingFraction: 0.10}, // below the 0.15 threshold
	}
	got, err := ChooseModel("high", snapshots)
	if err != nil {
		t.Fatalf("ChooseModel: %v", err)
	}
	if got != "claude-opus-4-6-thinking" {
		t.Errorf("got %q, want claude-opus-4-6-thinking (the non-Gemini option for high complexity)", got)
	}
}

func TestChooseModel_UsesTheLatestSnapshotWhenSeveralExist(t *testing.T) {
	// Snapshots are assumed ordered by timestamp, oldest first — the LAST
	// one in the slice is what decides, mirroring the removed Python's
	// gemini_snapshots[-1].
	snapshots := []model.UsageSnapshot{
		{ModelGroup: "Gemini Models", RemainingFraction: 0.05}, // old: low
		{ModelGroup: "Gemini Models", RemainingFraction: 0.80}, // latest: healthy
	}
	got, err := ChooseModel("low", snapshots)
	if err != nil {
		t.Fatalf("ChooseModel: %v", err)
	}
	if got != "gemini-3.8-flash-low" {
		t.Errorf("got %q, want gemini-3.8-flash-low (latest snapshot is healthy)", got)
	}
}

func TestChooseModel_RejectsUnknownComplexity(t *testing.T) {
	_, err := ChooseModel("extreme", nil)
	if err == nil {
		t.Fatal("expected an error for an unknown complexity level")
	}
}
