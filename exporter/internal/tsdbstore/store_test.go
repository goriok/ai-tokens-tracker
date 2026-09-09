package tsdbstore

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
)

var fixedTime = time.Date(2026, 9, 9, 12, 0, 0, 0, time.UTC)

func sample(metric string, delta float64, offset time.Duration) metrics.Sample {
	return metrics.Sample{
		Metric:    metric,
		Labels:    metrics.Labels{{Name: "model", Value: "a"}},
		Timestamp: fixedTime.Add(offset),
		Value:     delta,
	}
}

func TestOpen_CreatesLogFileAndDir(t *testing.T) {
	dir := t.TempDir()
	tsdbDir := filepath.Join(dir, "tsdb")

	s, err := Open(tsdbDir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer s.Close()

	if _, err := os.Stat(filepath.Join(tsdbDir, logFileName)); err != nil {
		t.Errorf("expected log file to exist: %v", err)
	}
}

func TestAppendBatch_WritesAndPersistsAcrossReopen(t *testing.T) {
	dir := t.TempDir()

	s, err := Open(dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	samples := []metrics.Sample{
		sample(metrics.TokensTotal, 10, 0),
		sample(metrics.TokensTotal, 15, time.Second),
	}
	result, err := s.AppendBatch(samples)
	if err != nil {
		t.Fatalf("AppendBatch: %v", err)
	}
	if result.Written != 2 {
		t.Errorf("Written = %d, want 2", result.Written)
	}
	if err := s.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	// Reopen — the log should replay and the last value should be recoverable.
	s2, err := Open(dir)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer s2.Close()

	acc := metrics.NewAccumulator()
	s2.SeedAccumulator(acc)

	// Applying a further delta of 5 should continue from the persisted 15,
	// not reset to 0 — this is the whole point of seeding on restart.
	got := acc.Apply(metrics.RawSample{
		Metric:    metrics.TokensTotal,
		Labels:    metrics.Labels{{Name: "model", Value: "a"}},
		Timestamp: fixedTime.Add(2 * time.Second),
		Delta:     5,
	})
	if got.Value != 20 {
		t.Errorf("got.Value = %v, want 20 (persisted 15 + delta 5)", got.Value)
	}
}

func TestAppendBatch_AppendsWithoutTruncating(t *testing.T) {
	dir := t.TempDir()

	s1, err := Open(dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if _, err := s1.AppendBatch([]metrics.Sample{sample(metrics.TokensTotal, 1, 0)}); err != nil {
		t.Fatalf("AppendBatch: %v", err)
	}
	s1.Close()

	s2, err := Open(dir)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	if _, err := s2.AppendBatch([]metrics.Sample{sample(metrics.TokensTotal, 2, time.Second)}); err != nil {
		t.Fatalf("AppendBatch: %v", err)
	}
	s2.Close()

	data, err := os.ReadFile(filepath.Join(dir, logFileName))
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	lines := 0
	for _, b := range data {
		if b == '\n' {
			lines++
		}
	}
	if lines != 2 {
		t.Errorf("log has %d lines, want 2 (both sessions' writes preserved)", lines)
	}
}

func TestReplay_SkipsCorruptTrailingLine(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, logFileName)
	if err := os.WriteFile(path, []byte(`{"metric":"aitokens_tokens_total","labels":[{"Name":"model","Value":"a"}],"ts_ms":1000,"value":42}`+"\n"+`{"metric":"aitokens_tokens_total`), 0o600); err != nil {
		t.Fatalf("write fixture: %v", err)
	}

	last, err := replay(path)
	if err != nil {
		t.Fatalf("replay: %v", err)
	}
	key := metrics.SeriesKey("aitokens_tokens_total", metrics.Labels{{Name: "model", Value: "a"}})
	if last[key].Value != 42 {
		t.Errorf("last[key].Value = %v, want 42 (valid line recovered despite corrupt trailing line)", last[key].Value)
	}
}

func TestSnapshot_ReturnsOneEntryPerSeriesWithLatestValue(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer s.Close()

	// Same series (model=a) written twice — Snapshot must report only the
	// latest value, not both, and not double-count as two series.
	if _, err := s.AppendBatch([]metrics.Sample{
		sample(metrics.TokensTotal, 10, 0),
		sample(metrics.TokensTotal, 25, time.Second), // same labels, later write
	}); err != nil {
		t.Fatalf("AppendBatch: %v", err)
	}
	// A distinct series (model=b) to confirm Snapshot doesn't collapse
	// different series together.
	other := metrics.Sample{
		Metric:    metrics.TokensTotal,
		Labels:    metrics.Labels{{Name: "model", Value: "b"}},
		Timestamp: fixedTime,
		Value:     99,
	}
	if _, err := s.AppendBatch([]metrics.Sample{other}); err != nil {
		t.Fatalf("AppendBatch: %v", err)
	}

	snap := s.Snapshot()
	if len(snap) != 2 {
		t.Fatalf("len(snap) = %d, want 2 (one per distinct series)", len(snap))
	}

	byModel := map[string]float64{}
	for _, sm := range snap {
		for _, l := range sm.Labels {
			if l.Name == "model" {
				byModel[l.Value] = sm.Value
			}
		}
	}
	if byModel["a"] != 25 {
		t.Errorf(`byModel["a"] = %v, want 25 (latest write, not the first)`, byModel["a"])
	}
	if byModel["b"] != 99 {
		t.Errorf(`byModel["b"] = %v, want 99`, byModel["b"])
	}
}

func TestSeedAccumulator_SkipsGauges(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer s.Close()

	gaugeSample := metrics.Sample{
		Metric:    metrics.QuotaRemainingRatio,
		Labels:    metrics.Labels{{Name: "model_group", Value: "gpt"}},
		Timestamp: fixedTime,
		Value:     0.9,
	}
	if _, err := s.AppendBatch([]metrics.Sample{gaugeSample}); err != nil {
		t.Fatalf("AppendBatch: %v", err)
	}

	acc := metrics.NewAccumulator()
	s.SeedAccumulator(acc)

	// A gauge Apply must reflect the raw delta, not anything seeded — Seed
	// is a no-op for gauges by design (see metrics.Accumulator.SeedByKey).
	got := acc.Apply(metrics.RawSample{
		Metric:    metrics.QuotaRemainingRatio,
		Labels:    metrics.Labels{{Name: "model_group", Value: "gpt"}},
		Timestamp: fixedTime,
		Delta:     0.3,
	})
	if got.Value != 0.3 {
		t.Errorf("got.Value = %v, want 0.3 (gauge seeding must be a no-op)", got.Value)
	}
}
