// Package httpapi serves the exporter's HTTP surface: /metrics in the
// Prometheus text exposition format, and /-/healthy for a liveness check.
// /metrics serves only current-state samples (Store.Snapshot) — the
// exporter's own "what does the token timeseries look like right now"
// view, scraped by VictoriaMetrics. Historical query (the backfilled
// years-deep data) has no HTTP surface here by design; see MADR-003 on why
// that's the tsdbstore log's job, not this endpoint's.
package httpapi

import (
	"fmt"
	"io"
	"net/http"
	"sort"
	"strconv"
	"strings"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/tsdbstore"
)

// SampleSource is the subset of *tsdbstore.Store this package depends on —
// narrowed to make the handler testable against a fake without pulling in
// a real Store (and its on-disk log) in unit tests.
type SampleSource interface {
	Snapshot() []metrics.Sample
}

var _ SampleSource = (*tsdbstore.Store)(nil)

// MetricsHandler returns an http.Handler serving src's current state in
// the Prometheus text exposition format (version 0.0.4 — the widely
// supported plain one; no need for OpenMetrics here).
func MetricsHandler(src SampleSource) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
		WriteMetrics(w, src.Snapshot())
	})
}

// WriteMetrics renders samples in Prometheus text exposition format,
// grouped by metric name with a HELP/TYPE header per group — this is the
// piece under test without needing an HTTP round-trip.
func WriteMetrics(w io.Writer, samples []metrics.Sample) {
	byMetric := map[string][]metrics.Sample{}
	for _, s := range samples {
		byMetric[s.Metric] = append(byMetric[s.Metric], s)
	}

	names := make([]string, 0, len(byMetric))
	for name := range byMetric {
		names = append(names, name)
	}
	sort.Strings(names) // deterministic output — stable diffs, stable tests

	for _, name := range names {
		group := byMetric[name]
		sort.Slice(group, func(i, j int) bool {
			return group[i].Labels.Key() < group[j].Labels.Key()
		})

		metricType := "counter"
		if metrics.IsGauge(name) {
			metricType = "gauge"
		}
		fmt.Fprintf(w, "# TYPE %s %s\n", name, metricType)
		for _, s := range group {
			fmt.Fprintf(w, "%s %s\n", formatSeries(name, s.Labels), formatValue(s.Value))
		}
	}
}

func formatSeries(name string, labels metrics.Labels) string {
	if len(labels) == 0 {
		return name
	}
	// Not %q here: Go's %q would re-escape what escapeLabelValue already
	// escaped (double-backslashing), and would use Go-string escaping rules
	// where they differ from the Prometheus text format's.
	parts := make([]string, len(labels))
	for i, l := range labels {
		parts[i] = fmt.Sprintf(`%s="%s"`, l.Name, escapeLabelValue(l.Value))
	}
	return name + "{" + strings.Join(parts, ",") + "}"
}

// escapeLabelValue escapes the two characters the Prometheus text format
// requires escaped inside a quoted label value: backslash and double quote
// (a literal newline would also need \n, but no label value in this
// exporter's model can contain one).
func escapeLabelValue(v string) string {
	v = strings.ReplaceAll(v, `\`, `\\`)
	v = strings.ReplaceAll(v, `"`, `\"`)
	return v
}

// formatValue renders a sample value without scientific notation — valid
// either way per the Prometheus text format, but token counts are always
// integral in practice, and 'f' keeps large ones (millions of tokens is a
// realistic daily total) human-readable in raw /metrics output.
func formatValue(v float64) string {
	return strconv.FormatFloat(v, 'f', -1, 64)
}
