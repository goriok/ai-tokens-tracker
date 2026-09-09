// Package ingest orchestrates sqlitesource -> metrics -> tsdbstore, in the
// two modes MADR-003 documents: a one-time Backfill with samples sorted
// globally by timestamp, and a recurring Incremental ingest that sorts only
// within each batch and relies on tsdbstore's tolerance for the small
// (~9-minute measured worst case in steady state) residual out-of-order lag
// between batches.
package ingest

import (
	"fmt"
	"sort"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/checkpoint"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/sqlitesource"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/tsdbstore"
)

// Result summarizes one ingest run (backfill or incremental cycle) across
// all 4 source tables, for logging and for the aitokens_ingest_* metrics
// (Phase 4/5 wiring — not emitted yet by this package itself).
type Result struct {
	RawSamples    int
	BadRows       int // unparseable timestamps, skipped at the sqlitesource layer
	Written       int
	NewCheckpoint checkpoint.State
}

// collectRawSamples reads every row after each table's checkpoint cursor
// and maps it to RawSamples, without sorting or accumulating yet — shared
// by Backfill (which then sorts globally) and Incremental (which sorts per
// batch). afterID.* fields let a caller start from 0 (backfill) or from a
// prior checkpoint (incremental).
func collectRawSamples(src *sqlitesource.Source, after checkpoint.State) (raws []metrics.RawSample, badRows int, newCheckpoint checkpoint.State, err error) {
	newCheckpoint = after

	ccEvents, ccMax, ccBad, err := src.ClaudeCodeEventsSince(after.ClaudeCodeUsageEvents)
	if err != nil {
		return nil, 0, after, fmt.Errorf("read claude_code_usage_events: %w", err)
	}
	for _, e := range ccEvents {
		raws = append(raws, metrics.ClaudeCodeSamples(e)...)
	}
	newCheckpoint.ClaudeCodeUsageEvents = ccMax
	badRows += ccBad

	taskCalls, tcMax, tcBad, err := src.TaskCallsSince(after.TaskCalls)
	if err != nil {
		return nil, 0, after, fmt.Errorf("read task_calls: %w", err)
	}
	for _, c := range taskCalls {
		raws = append(raws, metrics.TaskCallSamples(c)...)
	}
	newCheckpoint.TaskCalls = tcMax
	badRows += tcBad

	copilotEvents, coMax, coBad, err := src.CopilotEventsSince(after.CopilotUsageEvents)
	if err != nil {
		return nil, 0, after, fmt.Errorf("read copilot_usage_events: %w", err)
	}
	for _, e := range copilotEvents {
		raws = append(raws, metrics.CopilotSamples(e)...)
	}
	newCheckpoint.CopilotUsageEvents = coMax
	badRows += coBad

	snapshots, usMax, usBad, err := src.UsageSnapshotsSince(after.UsageSnapshots)
	if err != nil {
		return nil, 0, after, fmt.Errorf("read usage_snapshots: %w", err)
	}
	for _, snap := range snapshots {
		raws = append(raws, metrics.UsageSnapshotSample(snap))
	}
	newCheckpoint.UsageSnapshots = usMax
	badRows += usBad

	return raws, badRows, newCheckpoint, nil
}

// sortByTimestamp orders raws by timestamp, stably — a stable sort matters
// here: two samples from the same series at the exact same source
// timestamp (rare, but see MADR-003's measured 2-collision case) keep their
// original relative order instead of being shuffled, which would make a
// re-run of the same input non-deterministic.
func sortByTimestamp(raws []metrics.RawSample) {
	sort.SliceStable(raws, func(i, j int) bool {
		return raws[i].Timestamp.Before(raws[j].Timestamp)
	})
}

// Backfill runs once, reading every row from id 0 in each table, sorting
// ALL of them globally by timestamp before appending — this is what makes
// the historical backfill correct without depending on any out-of-order
// window: the measured worst-case lag across the full history (23+ days,
// from transcripts discovered late) would blow past any window size that's
// still efficient for a TSDB. See MADR-003.
//
// Refuses to run if checkpoint.State already has BackfillCompletedAt set,
// unless force is true — backfill assumes an empty store and a fresh
// accumulator; running it twice would double-count into the same series.
func Backfill(src *sqlitesource.Source, store *tsdbstore.Store, cp checkpoint.State, force bool, completedAt string) (Result, error) {
	if cp.BackfillCompletedAt != "" && !force {
		return Result{}, fmt.Errorf("backfill already completed at %s (pass force to re-run)", cp.BackfillCompletedAt)
	}

	raws, badRows, newCheckpoint, err := collectRawSamples(src, checkpoint.State{})
	if err != nil {
		return Result{}, err
	}
	sortByTimestamp(raws)

	acc := metrics.NewAccumulator()
	samples := acc.ApplyAll(raws)

	appendResult, err := store.AppendBatch(samples)
	if err != nil {
		return Result{}, fmt.Errorf("append backfill batch: %w", err)
	}

	newCheckpoint.BackfillCompletedAt = completedAt
	return Result{
		RawSamples:    len(raws),
		BadRows:       badRows,
		Written:       appendResult.Written,
		NewCheckpoint: newCheckpoint,
	}, nil
}

// Incremental runs one cycle of ongoing ingestion: reads the delta since
// the given checkpoint, sorts only within this batch (correcting the small
// inversions from reading multiple transcripts in one cycle — see
// MADR-003's 252-inversion, 9-minute measured case), and appends. The
// accumulator must be the long-lived one seeded from the store on startup
// (tsdbstore.Store.SeedAccumulator) — passed in, not created here, so
// running totals persist correctly across cycles within one process.
func Incremental(src *sqlitesource.Source, store *tsdbstore.Store, acc *metrics.Accumulator, cp checkpoint.State) (Result, error) {
	raws, badRows, newCheckpoint, err := collectRawSamples(src, cp)
	if err != nil {
		return Result{}, err
	}
	sortByTimestamp(raws)

	samples := acc.ApplyAll(raws)

	appendResult, err := store.AppendBatch(samples)
	if err != nil {
		return Result{}, fmt.Errorf("append incremental batch: %w", err)
	}

	newCheckpoint.BackfillCompletedAt = cp.BackfillCompletedAt // carried forward unchanged
	return Result{
		RawSamples:    len(raws),
		BadRows:       badRows,
		Written:       appendResult.Written,
		NewCheckpoint: newCheckpoint,
	}, nil
}
