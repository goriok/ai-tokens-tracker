package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
)

var fixedTime = time.Date(2026, 9, 9, 12, 0, 0, 0, time.UTC)

func TestWriteMetrics_FormatsCounterAndGaugeCorrectly(t *testing.T) {
	samples := []metrics.Sample{
		{
			Metric: metrics.TokensTotal,
			Labels: metrics.Labels{
				{Name: "source", Value: "claude-code"},
				{Name: "model", Value: "claude-sonnet-5"},
				{Name: "token_type", Value: "input"},
			},
			Timestamp: fixedTime,
			Value:     173008,
		},
		{
			Metric:    metrics.QuotaRemainingRatio,
			Labels:    metrics.Labels{{Name: "model_group", Value: "gemini_models"}},
			Timestamp: fixedTime,
			Value:     0.42,
		},
	}

	var buf strings.Builder
	WriteMetrics(&buf, samples)
	out := buf.String()

	if !strings.Contains(out, "# TYPE "+metrics.TokensTotal+" counter") {
		t.Errorf("missing counter TYPE line, got:\n%s", out)
	}
	if !strings.Contains(out, "# TYPE "+metrics.QuotaRemainingRatio+" gauge") {
		t.Errorf("missing gauge TYPE line, got:\n%s", out)
	}
	if !strings.Contains(out, `aitokens_tokens_total{source="claude-code",model="claude-sonnet-5",token_type="input"} 173008`) {
		t.Errorf("missing or malformed counter sample line, got:\n%s", out)
	}
	if !strings.Contains(out, `aitokens_quota_remaining_ratio{model_group="gemini_models"} 0.42`) {
		t.Errorf("missing or malformed gauge sample line, got:\n%s", out)
	}
}

func TestWriteMetrics_EscapesQuotesAndBackslashesInLabelValues(t *testing.T) {
	samples := []metrics.Sample{
		{
			Metric:    metrics.TokensTotal,
			Labels:    metrics.Labels{{Name: "project", Value: `C:\weird"path`}},
			Timestamp: fixedTime,
			Value:     1,
		},
	}
	var buf strings.Builder
	WriteMetrics(&buf, samples)
	out := buf.String()

	if !strings.Contains(out, `project="C:\\weird\"path"`) {
		t.Errorf("label value not properly escaped, got:\n%s", out)
	}
}

func TestWriteMetrics_LargeValuesAvoidScientificNotation(t *testing.T) {
	// A realistic large token count (millions) — valid either way per the
	// Prometheus text format, but scientific notation is needlessly opaque
	// for a value that's always integral in this domain.
	samples := []metrics.Sample{
		{Metric: metrics.TokensTotal, Labels: metrics.Labels{{Name: "model", Value: "a"}}, Timestamp: fixedTime, Value: 7250637988},
	}
	var buf strings.Builder
	WriteMetrics(&buf, samples)
	out := buf.String()

	if strings.Contains(out, "e+") || strings.Contains(out, "e-") {
		t.Errorf("expected no scientific notation for a large token count, got:\n%s", out)
	}
	if !strings.Contains(out, `aitokens_tokens_total{model="a"} 7250637988`) {
		t.Errorf("missing expected plain-decimal value, got:\n%s", out)
	}
}

func TestWriteMetrics_NoLabelsOmitsBraces(t *testing.T) {
	samples := []metrics.Sample{
		{Metric: metrics.TokensTotal, Labels: nil, Timestamp: fixedTime, Value: 5},
	}
	var buf strings.Builder
	WriteMetrics(&buf, samples)
	out := buf.String()

	if !strings.Contains(out, "aitokens_tokens_total 5\n") {
		t.Errorf("expected bare metric name with no braces, got:\n%s", out)
	}
}

func TestWriteMetrics_OutputIsDeterministic(t *testing.T) {
	// Same samples, different input order — output must be identical, since
	// map iteration order (byMetric grouping) is otherwise nondeterministic.
	a := []metrics.Sample{
		{Metric: metrics.TokensTotal, Labels: metrics.Labels{{Name: "model", Value: "b"}}, Timestamp: fixedTime, Value: 2},
		{Metric: metrics.TokensTotal, Labels: metrics.Labels{{Name: "model", Value: "a"}}, Timestamp: fixedTime, Value: 1},
		{Metric: metrics.QuotaRemainingRatio, Labels: metrics.Labels{{Name: "model_group", Value: "x"}}, Timestamp: fixedTime, Value: 0.5},
	}
	b := []metrics.Sample{a[2], a[0], a[1]}

	var bufA, bufB strings.Builder
	WriteMetrics(&bufA, a)
	WriteMetrics(&bufB, b)

	if bufA.String() != bufB.String() {
		t.Errorf("output differs by input order:\nA:\n%s\nB:\n%s", bufA.String(), bufB.String())
	}
}

type fakeSource struct{ samples []metrics.Sample }

func (f fakeSource) Snapshot() []metrics.Sample { return f.samples }

func TestMetricsHandler_ServesContentTypeAndBody(t *testing.T) {
	src := fakeSource{samples: []metrics.Sample{
		{Metric: metrics.TokensTotal, Labels: metrics.Labels{{Name: "model", Value: "a"}}, Timestamp: fixedTime, Value: 42},
	}}

	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	MetricsHandler(src).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
	ct := rec.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "text/plain") {
		t.Errorf("Content-Type = %q, want text/plain prefix", ct)
	}
	if !strings.Contains(rec.Body.String(), `aitokens_tokens_total{model="a"} 42`) {
		t.Errorf("body missing expected sample, got:\n%s", rec.Body.String())
	}
}

func TestHealthHandler_ReturnsOK(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/-/healthy", nil)
	rec := httptest.NewRecorder()
	HealthHandler().ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}
