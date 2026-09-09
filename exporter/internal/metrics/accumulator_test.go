package metrics

import (
	"testing"
	"time"
)

func rawToken(delta float64, secondsOffset int) RawSample {
	return RawSample{
		Metric:    TokensTotal,
		Labels:    Labels{{Name: "source", Value: "claude-code"}, {Name: "token_type", Value: TokenTypeInput}},
		Timestamp: fixedTime.Add(time.Duration(secondsOffset) * time.Second),
		Delta:     delta,
	}
}

func TestAccumulator_CounterIsMonotonicRunningTotal(t *testing.T) {
	acc := NewAccumulator()

	s1 := acc.Apply(rawToken(10, 0))
	s2 := acc.Apply(rawToken(5, 1))
	s3 := acc.Apply(rawToken(0, 2))

	if s1.Value != 10 {
		t.Errorf("s1.Value = %v, want 10", s1.Value)
	}
	if s2.Value != 15 {
		t.Errorf("s2.Value = %v, want 15 (10+5)", s2.Value)
	}
	if s3.Value != 15 {
		t.Errorf("s3.Value = %v, want 15 (unchanged by a zero delta)", s3.Value)
	}
	if s2.Value < s1.Value || s3.Value < s2.Value {
		t.Fatal("counter values must be non-decreasing within a series")
	}
}

func TestAccumulator_SeparateSeriesHaveIndependentTotals(t *testing.T) {
	acc := NewAccumulator()
	a := RawSample{Metric: TokensTotal, Labels: Labels{{Name: "model", Value: "a"}}, Timestamp: fixedTime, Delta: 10}
	b := RawSample{Metric: TokensTotal, Labels: Labels{{Name: "model", Value: "b"}}, Timestamp: fixedTime, Delta: 100}

	sa := acc.Apply(a)
	sb := acc.Apply(b)
	sa2 := acc.Apply(a)

	if sa.Value != 10 || sb.Value != 100 {
		t.Fatalf("got sa=%v sb=%v, want independent totals 10 and 100", sa.Value, sb.Value)
	}
	if sa2.Value != 20 {
		t.Errorf("sa2.Value = %v, want 20 (series a's own total, unaffected by series b)", sa2.Value)
	}
}

func TestAccumulator_GaugesAreNeverAccumulated(t *testing.T) {
	acc := NewAccumulator()
	raw := RawSample{Metric: QuotaRemainingRatio, Labels: Labels{{Name: "model_group", Value: "gpt"}}, Timestamp: fixedTime, Delta: 0.9}

	s1 := acc.Apply(raw)
	raw.Delta = 0.3 // quota went down — a gauge must reflect this, not add to a running total
	s2 := acc.Apply(raw)

	if s1.Value != 0.9 {
		t.Errorf("s1.Value = %v, want 0.9", s1.Value)
	}
	if s2.Value != 0.3 {
		t.Errorf("s2.Value = %v, want 0.3 (gauges report the raw value, not a sum)", s2.Value)
	}
}

func TestAccumulator_SeedRecoversStateAcrossRestart(t *testing.T) {
	// Simulates a process restart: a fresh Accumulator seeded with the
	// TSDB's last known value for a series must continue from there, not
	// from 0 — otherwise a restart manufactures a fake counter drop.
	acc := NewAccumulator()
	labels := Labels{{Name: "model", Value: "a"}}
	acc.Seed(TokensTotal, labels, 1000)

	s := acc.Apply(RawSample{Metric: TokensTotal, Labels: labels, Timestamp: fixedTime, Delta: 50})

	if s.Value != 1050 {
		t.Errorf("s.Value = %v, want 1050 (seeded 1000 + delta 50)", s.Value)
	}
}

func TestAccumulator_SeedIsNoOpForGauges(t *testing.T) {
	acc := NewAccumulator()
	labels := Labels{{Name: "model_group", Value: "gpt"}}
	acc.Seed(QuotaRemainingRatio, labels, 999) // must be ignored — gauges have no running total

	s := acc.Apply(RawSample{Metric: QuotaRemainingRatio, Labels: labels, Timestamp: fixedTime, Delta: 0.5})
	if s.Value != 0.5 {
		t.Errorf("s.Value = %v, want 0.5 (Seed must not affect gauge values)", s.Value)
	}
}

func TestAccumulator_ApplyAllPreservesOrderAndRunningTotals(t *testing.T) {
	acc := NewAccumulator()
	raws := []RawSample{rawToken(1, 0), rawToken(2, 1), rawToken(3, 2)}

	samples := acc.ApplyAll(raws)

	want := []float64{1, 3, 6}
	for i, s := range samples {
		if s.Value != want[i] {
			t.Errorf("samples[%d].Value = %v, want %v", i, s.Value, want[i])
		}
	}
}
