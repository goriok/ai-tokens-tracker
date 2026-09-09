package ingest

import (
	"testing"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/adapters/claudecode"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/adapters/copilot"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/checkpoint"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/tsdbstore"
)

// fakeQuotaRunner is the seam for the removed subprocess dependency —
// FetchQuota's own parsing logic is tested in adapters/agycli; here it's a
// collaborator ingest.Backfill/Incremental must call and fold in.
type fakeQuotaRunner struct {
	snapshots []model.UsageSnapshot
	err       error
}

func (f fakeQuotaRunner) FetchQuota() ([]model.UsageSnapshot, error) {
	return f.snapshots, f.err
}

func openTempStore(t *testing.T) *tsdbstore.Store {
	t.Helper()
	store, err := tsdbstore.Open(t.TempDir())
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

// claudecode's own testdata/projects fixture (3 events across req-1,
// req-2, req-3, with req-3 timestamped earlier than the other two despite
// being read last — the out-of-order case Backfill must handle by sorting
// globally) and copilot's testdata/session-state fixture (1 completed
// session) are reused here rather than duplicated, so there's one place
// that defines what "the fixture" contains.
const (
	claudeCodeFixtureDir = "../adapters/claudecode/testdata/projects"
	copilotFixtureDir    = "../adapters/copilot/testdata/session-state"
)

func TestBackfill_ReadsAllSourcesAndSortsGlobally(t *testing.T) {
	ccReader := claudecode.NewReader(claudeCodeFixtureDir)
	copilotReader := copilot.NewReader(copilotFixtureDir)
	quota := fakeQuotaRunner{}
	store := openTempStore(t)

	result, err := Backfill(ccReader, copilotReader, quota, store, checkpoint.State{}, false, "2026-09-09T18:00:00Z")
	if err != nil {
		t.Fatalf("Backfill: %v", err)
	}

	if result.NewCheckpoint.BackfillCompletedAt != "2026-09-09T18:00:00Z" {
		t.Errorf("BackfillCompletedAt = %q, want the completedAt passed in", result.NewCheckpoint.BackfillCompletedAt)
	}
	if result.Written != result.RawSamples {
		t.Errorf("Written = %d, want %d (all samples land within the fresh store)", result.Written, result.RawSamples)
	}

	// req-1's series (proj-a, claude-sonnet-5, named session) must have its
	// full running total intact after backfill, regardless of the fact that
	// req-3 (an earlier-timestamped, later-discovered event) was read after
	// it — proving the sort-before-append discipline survived the port from
	// sqlitesource to these file-based adapters.
	acc := metrics.NewAccumulator()
	store.SeedAccumulator(acc)
	got := acc.Apply(metrics.RawSample{
		Metric: metrics.TokensTotal,
		Labels: metrics.Labels{
			{Name: "source", Value: "claude-code"},
			{Name: "model", Value: "claude-sonnet-5"},
			{Name: "project", Value: "proj-a"},
			{Name: "git_branch", Value: "main"},
			{Name: "agent_kind", Value: metrics.AgentKindMain},
			{Name: "session_name", Value: "morning-refactor"},
			{Name: "token_type", Value: metrics.TokenTypeInput},
		},
		Delta: 0,
	})
	if got.Value != 100 {
		t.Errorf("req-1 series running total = %v, want 100", got.Value)
	}
}

func TestBackfill_RefusesToRerunWithoutForce(t *testing.T) {
	ccReader := claudecode.NewReader(claudeCodeFixtureDir)
	copilotReader := copilot.NewReader(copilotFixtureDir)
	store := openTempStore(t)

	completed := checkpoint.State{BackfillCompletedAt: "2026-09-01T00:00:00Z"}
	_, err := Backfill(ccReader, copilotReader, fakeQuotaRunner{}, store, completed, false, "2026-09-09T18:00:00Z")
	if err == nil {
		t.Fatal("expected an error when backfill has already completed and force is false")
	}
}

func TestBackfill_ForceAllowsRerun(t *testing.T) {
	ccReader := claudecode.NewReader(claudeCodeFixtureDir)
	copilotReader := copilot.NewReader(copilotFixtureDir)
	store := openTempStore(t)

	completed := checkpoint.State{BackfillCompletedAt: "2026-09-01T00:00:00Z"}
	_, err := Backfill(ccReader, copilotReader, fakeQuotaRunner{}, store, completed, true, "2026-09-09T18:00:00Z")
	if err != nil {
		t.Fatalf("Backfill with force=true: %v", err)
	}
}

func TestIncremental_CursorPreventsReprocessing(t *testing.T) {
	ccReader := claudecode.NewReader(claudeCodeFixtureDir)
	copilotReader := copilot.NewReader(copilotFixtureDir)
	store := openTempStore(t)
	acc := metrics.NewAccumulator()

	first, err := Incremental(ccReader, copilotReader, fakeQuotaRunner{}, store, acc, checkpoint.State{})
	if err != nil {
		t.Fatalf("Incremental cycle 1: %v", err)
	}
	if first.RawSamples == 0 {
		t.Fatal("cycle 1: expected some raw samples from the fixture, got 0")
	}

	second, err := Incremental(ccReader, copilotReader, fakeQuotaRunner{}, store, acc, first.NewCheckpoint)
	if err != nil {
		t.Fatalf("Incremental cycle 2: %v", err)
	}
	if second.RawSamples != 0 {
		t.Errorf("cycle 2 (advanced cursor): RawSamples = %d, want 0 (nothing new)", second.RawSamples)
	}
}

func TestIncremental_FoldsInQuotaSnapshots(t *testing.T) {
	ccReader := claudecode.NewReader(claudeCodeFixtureDir)
	copilotReader := copilot.NewReader(copilotFixtureDir)
	store := openTempStore(t)
	acc := metrics.NewAccumulator()

	quota := fakeQuotaRunner{snapshots: []model.UsageSnapshot{
		{ModelGroup: "Gemini Models", RemainingFraction: 0.5},
	}}

	result, err := Incremental(ccReader, copilotReader, quota, store, acc, checkpoint.State{})
	if err != nil {
		t.Fatalf("Incremental: %v", err)
	}

	snap := store.Snapshot()
	var found bool
	for _, s := range snap {
		if s.Metric == metrics.QuotaRemainingRatio {
			found = true
			if s.Value != 0.5 {
				t.Errorf("quota sample value = %v, want 0.5", s.Value)
			}
		}
	}
	if !found {
		t.Error("expected a QuotaRemainingRatio sample in the store after Incremental")
	}
	if result.RawSamples == 0 {
		t.Error("expected RawSamples to include the quota snapshot on top of transcript events")
	}
}
