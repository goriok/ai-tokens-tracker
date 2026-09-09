// Package vmimport renders samples in VictoriaMetrics' JSON line import
// format and pushes them to its /api/v1/import endpoint. This exists
// because VictoriaMetrics scraping the exporter's /metrics only ever sees
// "now" (the Prometheus text format has no way to carry a sample's real
// past timestamp — see MADR-003) — so the historical backfill, which does
// have real timestamps in tsdbstore's log, needs a separate path with
// explicit timestamps to actually show up as history in vmui/PromQL
// instead of collapsing to the moment of import.
package vmimport

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sort"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
)

// line is one series' full time-value history, in the shape
// VictoriaMetrics' import endpoint expects:
// https://docs.victoriametrics.com/#how-to-import-time-series-data
type line struct {
	Metric     map[string]string `json:"metric"`
	Values     []float64         `json:"values"`
	Timestamps []int64           `json:"timestamps"`
}

// WriteLines groups samples by series and writes one JSON line per series,
// each carrying its full value/timestamp history in order — the format
// VictoriaMetrics' /api/v1/import (newline-delimited JSON) accepts.
// Samples for the same series must already be in timestamp order (true of
// tsdbstore.Store.AllSamples, which returns log order = append order =
// timestamp order per series by construction).
func WriteLines(w io.Writer, samples []metrics.Sample) error {
	bySeries := map[string]*line{}
	seriesOrder := []string{} // preserves first-seen order for deterministic output

	for _, s := range samples {
		key := metrics.SeriesKey(s.Metric, s.Labels)
		l, ok := bySeries[key]
		if !ok {
			m := map[string]string{"__name__": s.Metric}
			for _, lbl := range s.Labels {
				m[lbl.Name] = lbl.Value
			}
			l = &line{Metric: m}
			bySeries[key] = l
			seriesOrder = append(seriesOrder, key)
		}
		l.Values = append(l.Values, s.Value)
		l.Timestamps = append(l.Timestamps, s.Timestamp.UnixMilli())
	}

	sort.Strings(seriesOrder) // deterministic output regardless of input order
	enc := json.NewEncoder(w)
	for _, key := range seriesOrder {
		if err := enc.Encode(bySeries[key]); err != nil {
			return fmt.Errorf("encode series %s: %w", key, err)
		}
	}
	return nil
}

// Import POSTs samples to a running VictoriaMetrics' /api/v1/import
// endpoint at baseURL (e.g. "http://127.0.0.1:8428"). VictoriaMetrics
// accepts out-of-order and historical timestamps here unconditionally —
// unlike a Prometheus remote_write receiver, there's no window to worry
// about (see MADR-003's out-of-order discussion, which is about
// tsdbstore's own append order, not this import path).
func Import(baseURL string, samples []metrics.Sample) error {
	var buf bytes.Buffer
	if err := WriteLines(&buf, samples); err != nil {
		return err
	}

	resp, err := http.Post(baseURL+"/api/v1/import", "application/json", &buf)
	if err != nil {
		return fmt.Errorf("POST %s/api/v1/import: %w", baseURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("import failed: %s: %s", resp.Status, body)
	}
	return nil
}
