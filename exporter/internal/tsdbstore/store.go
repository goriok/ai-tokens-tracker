// Package tsdbstore is a minimal, self-contained timeseries store: an
// append-only log of samples plus an in-memory series index rebuilt on
// open. It exists in place of the embedded Prometheus TSDB
// (github.com/prometheus/prometheus/tsdb) — that dependency was tried and
// measured (go.sum 50→496 lines, ~44s clean build, from tsdb/db.go and
// tsdb/head.go importing prometheus/prometheus/config -> discovery, pulling
// in k8s.io/client-go and the AWS/Azure/GCP SDKs — intrinsic to the
// package, not prunable without a fork) and reverted; see MADR-003. This
// package accepts arbitrary sample timestamps (what /metrics can't
// express), which is the one property this project actually needs from a
// "TSDB": a place to hold the historical backfill. PromQL and rich
// querying live in VictoriaMetrics (scraping /metrics), not here — this
// store trades that away deliberately for a tiny go.sum.
package tsdbstore

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
)

const logFileName = "samples.log"

// record is the on-disk shape of one sample — one JSON object per line
// (append-only log, never rewritten in place).
type record struct {
	Metric      string         `json:"metric"`
	Labels      metrics.Labels `json:"labels"`
	TimestampMs int64          `json:"ts_ms"`
	Value       float64        `json:"value"`
}

// Store is an append-only samples log with an in-memory last-value index
// per series, sufficient for this project's volume (tens of thousands of
// samples/year across a few hundred series — see MADR-003's cardinality
// measurements). Not safe for concurrent use from multiple processes; a
// single exporter process owns the directory.
type Store struct {
	mu     sync.Mutex
	file   *os.File
	writer *bufio.Writer
	// last holds, per series (keyed by metrics.SeriesKey), the most recently
	// written sample in full — not just its value — so /metrics can be
	// served straight from this index without re-reading the log: current
	// state, no historical query support, matching the "current state
	// counters" role /metrics has here (see MADR-003).
	last map[string]metrics.Sample
}

// Open creates dir if needed and opens (or creates) the append-only log,
// replaying it once to rebuild the in-memory last-value index.
func Open(dir string) (*Store, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, fmt.Errorf("mkdir %s: %w", dir, err)
	}
	path := filepath.Join(dir, logFileName)

	last, err := replay(path)
	if err != nil {
		return nil, fmt.Errorf("replay %s: %w", path, err)
	}

	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open %s for append: %w", path, err)
	}

	return &Store{
		file:   f,
		writer: bufio.NewWriter(f),
		last:   last,
	}, nil
}

// replay reads every record in the log to rebuild the last-sample index.
// A missing file is not an error — a fresh store has none yet. A malformed
// trailing line (e.g. a crash mid-write) is skipped, not fatal — partial
// writes only ever happen at EOF, in the record currently being appended.
func replay(path string) (map[string]metrics.Sample, error) {
	last := make(map[string]metrics.Sample)

	f, err := os.Open(path)
	if os.IsNotExist(err) {
		return last, nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		var rec record
		if err := json.Unmarshal(scanner.Bytes(), &rec); err != nil {
			continue
		}
		last[metrics.SeriesKey(rec.Metric, rec.Labels)] = recordToSample(rec)
	}
	return last, scanner.Err()
}

func recordToSample(rec record) metrics.Sample {
	return metrics.Sample{
		Metric:    rec.Metric,
		Labels:    rec.Labels,
		Timestamp: time.UnixMilli(rec.TimestampMs).UTC(),
		Value:     rec.Value,
	}
}

// Close flushes and closes the log file.
func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.writer.Flush(); err != nil {
		return err
	}
	return s.file.Close()
}

// AppendResult reports what happened to one batch.
type AppendResult struct {
	Written int
}

// AppendBatch writes samples to the log in the order given and updates the
// in-memory last-value index. Callers should pre-sort samples by timestamp
// per series (metrics.Accumulator's running totals already require this) —
// this store itself doesn't reject or reorder anything by timestamp: unlike
// an embedded Prometheus TSDB it has no compaction step to protect, so
// out-of-order writes are unusual but not an error here. All-or-nothing per
// call in effect: on any write error mid-batch, the caller should treat the
// whole batch as unconfirmed and retry (the index may be partially updated,
// but the log itself — the source of truth on next Open's replay — reflects
// exactly what was actually flushed).
func (s *Store) AppendBatch(samples []metrics.Sample) (AppendResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	var result AppendResult
	for _, sample := range samples {
		rec := record{
			Metric:      sample.Metric,
			Labels:      sample.Labels,
			TimestampMs: sample.Timestamp.UnixMilli(),
			Value:       sample.Value,
		}
		line, err := json.Marshal(rec)
		if err != nil {
			return result, fmt.Errorf("marshal sample for %s: %w", sample.Metric, err)
		}
		if _, err := s.writer.Write(line); err != nil {
			return result, fmt.Errorf("write sample for %s: %w", sample.Metric, err)
		}
		if err := s.writer.WriteByte('\n'); err != nil {
			return result, fmt.Errorf("write newline: %w", err)
		}
		s.last[metrics.SeriesKey(sample.Metric, sample.Labels)] = sample
		result.Written++
	}
	if err := s.writer.Flush(); err != nil {
		return result, fmt.Errorf("flush: %w", err)
	}
	if err := s.file.Sync(); err != nil {
		return result, fmt.Errorf("fsync: %w", err)
	}
	return result, nil
}

// SeedAccumulator pre-populates acc with every series' last known value
// from this store's log — call once on startup, before the first
// incremental ingest cycle, so a process restart doesn't reset a counter to
// 0 and manufacture a fake drop that rate() would misread as a reset.
// Gauge series are skipped (Accumulator.SeedByKey is a no-op for them) —
// this store doesn't need to know which metric names are gauges beyond
// asking metrics.IsGauge, keeping that classification in one place.
func (s *Store) SeedAccumulator(acc *metrics.Accumulator) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for key, sample := range s.last {
		acc.SeedByKey(key, metrics.IsGauge(sample.Metric), sample.Value)
	}
}

// Snapshot returns the current state — the most recent sample of every
// series this store has ever seen — for serving /metrics. The returned
// slice is a copy; callers may sort or iterate it freely without any lock
// held on the store.
func (s *Store) Snapshot() []metrics.Sample {
	s.mu.Lock()
	defer s.mu.Unlock()
	samples := make([]metrics.Sample, 0, len(s.last))
	for _, sample := range s.last {
		samples = append(samples, sample)
	}
	return samples
}
