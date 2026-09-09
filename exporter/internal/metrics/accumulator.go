package metrics

import "time"

// gaugeMetrics are reported as-is (Delta is the actual value), never
// accumulated — a quota fraction or a measured/unmeasured flag has no
// meaningful "running total".
var gaugeMetrics = map[string]bool{
	QuotaRemainingRatio:   true,
	CacheCreationMeasured: true,
}

// Sample is one point ready to append to the TSDB: for a counter metric,
// Value is the running total (not the delta the RawSample carried); for a
// gauge metric, Value is RawSample.Delta unchanged.
type Sample struct {
	Metric    string
	Labels    Labels
	Timestamp time.Time
	Value     float64
}

// Accumulator turns a stream of RawSamples, applied in non-decreasing
// timestamp order, into monotonic counter Samples — required because a
// Prometheus counter must never decrease within a series, but the source
// data arrives as per-event deltas (one row per request), not running
// totals. Callers MUST feed samples for a given series in timestamp order;
// see ingest/backfill (global sort) and ingest/incremental (per-batch sort
// + a bounded out-of-order window in the TSDB) for how that's guaranteed.
type Accumulator struct {
	totals map[string]float64 // series key -> running total, counters only
}

func NewAccumulator() *Accumulator {
	return &Accumulator{totals: make(map[string]float64)}
}

// Seed pre-populates a counter series' running total — used on startup to
// recover state from the TSDB's own last value, so a process restart
// doesn't reset the counter to 0 and manufacture a fake drop that rate()
// would misread as a counter reset.
func (a *Accumulator) Seed(metric string, labels Labels, total float64) {
	if gaugeMetrics[metric] {
		return // gauges have no running total to seed
	}
	a.totals[labels.Key()+"|"+metric] = total
}

// Apply converts one RawSample into an appendable Sample, updating the
// running total for counter metrics as a side effect.
func (a *Accumulator) Apply(raw RawSample) Sample {
	if gaugeMetrics[raw.Metric] {
		return Sample{Metric: raw.Metric, Labels: raw.Labels, Timestamp: raw.Timestamp, Value: raw.Delta}
	}
	key := raw.Labels.Key() + "|" + raw.Metric
	a.totals[key] += raw.Delta
	return Sample{Metric: raw.Metric, Labels: raw.Labels, Timestamp: raw.Timestamp, Value: a.totals[key]}
}

// ApplyAll converts a batch of RawSamples in order — a thin convenience
// over repeated Apply, kept explicit about the ordering requirement.
func (a *Accumulator) ApplyAll(raws []RawSample) []Sample {
	samples := make([]Sample, len(raws))
	for i, raw := range raws {
		samples[i] = a.Apply(raw)
	}
	return samples
}
