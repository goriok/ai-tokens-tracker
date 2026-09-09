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

// SeriesKey returns the same series identity Apply/Seed key on internally —
// exported so a store (tsdbstore) can rebuild a series' key from what it
// persisted without duplicating the "metric+labels" concatenation rule.
func SeriesKey(metric string, labels Labels) string {
	return metric + "|" + labels.Key()
}

// Seed pre-populates a counter series' running total — used on startup to
// recover state from the store's own last value, so a process restart
// doesn't reset the counter to 0 and manufacture a fake drop that rate()
// would misread as a counter reset. metric/labels here are only used to
// check the gauge exemption; the total is keyed by SeriesKey(metric, labels).
func (a *Accumulator) Seed(metric string, labels Labels, total float64) {
	if gaugeMetrics[metric] {
		return // gauges have no running total to seed
	}
	a.totals[SeriesKey(metric, labels)] = total
}

// SeedByKey is Seed for a caller that already has the series key (e.g. a
// store replaying its log, which persists metric+labels but not necessarily
// as a live Labels value) and separately knows whether it's a gauge metric.
func (a *Accumulator) SeedByKey(key string, isGauge bool, total float64) {
	if isGauge {
		return
	}
	a.totals[key] = total
}

// Apply converts one RawSample into an appendable Sample, updating the
// running total for counter metrics as a side effect.
func (a *Accumulator) Apply(raw RawSample) Sample {
	if gaugeMetrics[raw.Metric] {
		return Sample{Metric: raw.Metric, Labels: raw.Labels, Timestamp: raw.Timestamp, Value: raw.Delta}
	}
	key := SeriesKey(raw.Metric, raw.Labels)
	a.totals[key] += raw.Delta
	return Sample{Metric: raw.Metric, Labels: raw.Labels, Timestamp: raw.Timestamp, Value: a.totals[key]}
}

// IsGauge reports whether metric is a gauge (reported as-is) rather than an
// accumulated counter — exposed so callers outside this package (a store
// replaying its log) can classify a metric name without duplicating the
// gaugeMetrics table.
func IsGauge(metric string) bool {
	return gaugeMetrics[metric]
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
