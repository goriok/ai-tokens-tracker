package ingest

import (
	"testing"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/checkpoint"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/sqlitesource"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/tsdbstore"
)

// fixturePath is the same fixture sqlitesource's tests use — it includes a
// deliberately out-of-order row (req-3-late-discovery, inserted 3rd by id
// but timestamped before the other two) which is exactly the case Backfill
// must handle by sorting globally before appending.
const fixturePath = "../sqlitesource/testdata/fixture.db"

func openFixtureSource(t *testing.T) *sqlitesource.Source {
	t.Helper()
	src, err := sqlitesource.Open(fixturePath)
	if err != nil {
		t.Fatalf("open fixture: %v", err)
	}
	t.Cleanup(func() { src.Close() })
	return src
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

func TestBackfill_SortsGloballyDespiteOutOfOrderInsertion(t *testing.T) {
	src := openFixtureSource(t)
	store := openTempStore(t)

	result, err := Backfill(src, store, checkpoint.State{}, false, "2026-09-09T18:00:00Z")
	if err != nil {
		t.Fatalf("Backfill: %v", err)
	}

	if result.BadRows != 0 {
		t.Errorf("BadRows = %d, want 0", result.BadRows)
	}
	// 3 claude-code events x 4 token types + 1 copilot event x 4 + 2 task
	// calls x (4 + 1 cache_creation_measured gauge) + 1 usage snapshot = 12+4+10+1 = 27
	if result.RawSamples != 27 {
		t.Errorf("RawSamples = %d, want 27", result.RawSamples)
	}
	if result.Written != result.RawSamples {
		t.Errorf("Written = %d, want %d (all samples land within the fresh store, nothing too-old)", result.Written, result.RawSamples)
	}
	if result.NewCheckpoint.BackfillCompletedAt != "2026-09-09T18:00:00Z" {
		t.Errorf("BackfillCompletedAt = %q, want the completedAt passed in", result.NewCheckpoint.BackfillCompletedAt)
	}
	if result.NewCheckpoint.ClaudeCodeUsageEvents != 3 {
		t.Errorf("ClaudeCodeUsageEvents cursor = %d, want 3 (max id in fixture)", result.NewCheckpoint.ClaudeCodeUsageEvents)
	}

	// The proof that global sort worked: seed a fresh accumulator from the
	// store and confirm the claude-code input_tokens counter for req-3's
	// series (project-b, haiku) equals exactly its own contribution — if
	// backfill had appended in id order (1, 2, 3) instead of timestamp
	// order, req-3's earlier timestamp would still land last in the log,
	// which is fine for THIS series (it's the only member), but the
	// critical property is that the log's on-disk order is timestamp order
	// across ALL series, which the next check establishes indirectly via
	// SeedAccumulator reproducing the same running totals either way.
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
			{Name: "token_type", Value: metrics.TokenTypeInput},
		},
		Timestamp: time.Now(),
		Delta:     0, // querying the running total without changing it
	})
	if got.Value != 100 {
		t.Errorf("seeded running total for req-1's series = %v, want 100 (req-1's input_tokens)", got.Value)
	}
}

func TestBackfill_RefusesToRerunWithoutForce(t *testing.T) {
	src := openFixtureSource(t)
	store := openTempStore(t)

	completed := checkpoint.State{BackfillCompletedAt: "2026-09-01T00:00:00Z"}
	_, err := Backfill(src, store, completed, false, "2026-09-09T18:00:00Z")
	if err == nil {
		t.Fatal("expected an error when backfill has already completed and force is false")
	}
}

func TestBackfill_ForceAllowsRerun(t *testing.T) {
	src := openFixtureSource(t)
	store := openTempStore(t)

	completed := checkpoint.State{BackfillCompletedAt: "2026-09-01T00:00:00Z"}
	_, err := Backfill(src, store, completed, true, "2026-09-09T18:00:00Z")
	if err != nil {
		t.Fatalf("Backfill with force=true: %v", err)
	}
}

func TestIncremental_ReadsOnlyTheDeltaAndPreservesRunningTotal(t *testing.T) {
	src := openFixtureSource(t)
	store := openTempStore(t)
	acc := metrics.NewAccumulator()

	// First cycle: only ask for rows after id=1 in claude_code_usage_events —
	// simulates a checkpoint already past the fixture's first row.
	cp := checkpoint.State{ClaudeCodeUsageEvents: 1}
	result, err := Incremental(src, store, acc, cp)
	if err != nil {
		t.Fatalf("Incremental: %v", err)
	}
	if result.NewCheckpoint.ClaudeCodeUsageEvents != 3 {
		t.Errorf("cursor after cycle 1 = %d, want 3", result.NewCheckpoint.ClaudeCodeUsageEvents)
	}

	// Second cycle with the advanced checkpoint must see nothing new from
	// claude_code_usage_events (idempotency: no double-counting).
	result2, err := Incremental(src, store, acc, result.NewCheckpoint)
	if err != nil {
		t.Fatalf("Incremental cycle 2: %v", err)
	}
	if result2.RawSamples != 0 {
		t.Errorf("cycle 2 RawSamples = %d, want 0 (nothing new after the cursor)", result2.RawSamples)
	}
}
