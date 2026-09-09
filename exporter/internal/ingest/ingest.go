// Package ingest orchestrates the ports.* readers -> metrics -> tsdbstore,
// in the two modes MADR-003/MADR-004 document: a one-time Backfill with
// samples sorted globally by timestamp, and a recurring Incremental ingest
// that sorts only within each batch and relies on tsdbstore's tolerance
// for the small (~9-minute measured worst case in steady state) residual
// out-of-order lag between batches. Depends only on the ports interfaces,
// never on a concrete adapter — the same hexagonal discipline
// adapters/claude_code_transcript_reader.py's removed Python callers
// followed.
package ingest

import (
	"fmt"
	"sort"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/checkpoint"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/ports"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/tsdbstore"
)

// Result summarizes one ingest run (backfill or incremental cycle) across
// every source, for logging and for the aitokens_ingest_* metrics.
type Result struct {
	RawSamples    int
	Written       int
	NewCheckpoint checkpoint.State
}

// collectRawSamples reads every source's new-since-cursor data and maps it
// to RawSamples, without sorting or accumulating yet — shared by Backfill
// (which then sorts globally) and Incremental (which sorts per batch).
//
// task_calls (tracked -p invocations) has no port here yet — it has no
// file- or subprocess-backed source of its own the way claude-code/copilot
// transcripts and the agy quota poll do; it's wired in once a tracked-call
// subcommand exists to produce it directly into tsdbstore, not through this
// read-then-ingest path.
func collectRawSamples(
	ccReader ports.ClaudeCodeTranscriptReader,
	copilotReader ports.CopilotTranscriptReader,
	quota ports.QuotaRunner,
	after checkpoint.State,
) (raws []metrics.RawSample, newCheckpoint checkpoint.State, err error) {
	newCheckpoint = after

	ccEvents, ccTitles, newFileCursors, err := ccReader.ReadNewEvents(after.ClaudeCodeFileCursors)
	if err != nil {
		return nil, after, fmt.Errorf("read claude-code transcripts: %w", err)
	}
	titleBySession := make(map[string]string, len(ccTitles))
	for _, t := range ccTitles {
		titleBySession[t.SessionID] = t.Title
	}
	for _, e := range ccEvents {
		raws = append(raws, metrics.ClaudeCodeSamples(e, titleBySession[e.SessionID])...)
	}
	newCheckpoint.ClaudeCodeFileCursors = newFileCursors

	copilotEvents, _, newReadSessions, err := copilotReader.ReadNewEvents(after.CopilotReadSessions)
	if err != nil {
		return nil, after, fmt.Errorf("read copilot transcripts: %w", err)
	}
	for _, e := range copilotEvents {
		raws = append(raws, metrics.CopilotSamples(e)...)
	}
	newCheckpoint.CopilotReadSessions = newReadSessions

	snapshots, err := quota.FetchQuota()
	if err != nil {
		return nil, after, fmt.Errorf("fetch agy quota: %w", err)
	}
	for _, snap := range snapshots {
		raws = append(raws, metrics.UsageSnapshotSample(snap))
	}

	return raws, newCheckpoint, nil
}

// sortByTimestamp orders raws by timestamp, stably — a stable sort matters
// here: two samples from the same series at the exact same source
// timestamp keep their original relative order instead of being shuffled,
// which would make a re-run of the same input non-deterministic.
func sortByTimestamp(raws []metrics.RawSample) {
	sort.SliceStable(raws, func(i, j int) bool {
		return raws[i].Timestamp.Before(raws[j].Timestamp)
	})
}

// Backfill runs once, reading every available transcript event from
// scratch (an empty cursor state) and sorting ALL of them globally by
// timestamp before appending — this is what makes the historical backfill
// correct without depending on any out-of-order window: the measured
// worst-case lag across the full history (23+ days, from transcripts
// discovered late) would blow past any window size that's still efficient
// for a TSDB. See MADR-003.
//
// Refuses to run if checkpoint.State already has BackfillCompletedAt set,
// unless force is true — backfill assumes an empty store and a fresh
// accumulator; running it twice would double-count into the same series.
func Backfill(
	ccReader ports.ClaudeCodeTranscriptReader,
	copilotReader ports.CopilotTranscriptReader,
	quota ports.QuotaRunner,
	store *tsdbstore.Store,
	cp checkpoint.State,
	force bool,
	completedAt string,
) (Result, error) {
	if cp.BackfillCompletedAt != "" && !force {
		return Result{}, fmt.Errorf("backfill already completed at %s (pass force to re-run)", cp.BackfillCompletedAt)
	}

	raws, newCheckpoint, err := collectRawSamples(ccReader, copilotReader, quota, checkpoint.State{})
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
func Incremental(
	ccReader ports.ClaudeCodeTranscriptReader,
	copilotReader ports.CopilotTranscriptReader,
	quota ports.QuotaRunner,
	store *tsdbstore.Store,
	acc *metrics.Accumulator,
	cp checkpoint.State,
) (Result, error) {
	raws, newCheckpoint, err := collectRawSamples(ccReader, copilotReader, quota, cp)
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
		Written:       appendResult.Written,
		NewCheckpoint: newCheckpoint,
	}, nil
}
