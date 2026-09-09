package vmimport

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
)

var fixedTime = time.Date(2026, 9, 9, 12, 0, 0, 0, time.UTC)

func TestWriteLines_GroupsBySeriesWithFullHistory(t *testing.T) {
	samples := []metrics.Sample{
		{Metric: "aitokens_tokens_total", Labels: metrics.Labels{{Name: "model", Value: "a"}}, Timestamp: fixedTime, Value: 10},
		{Metric: "aitokens_tokens_total", Labels: metrics.Labels{{Name: "model", Value: "a"}}, Timestamp: fixedTime.Add(time.Hour), Value: 25},
		{Metric: "aitokens_tokens_total", Labels: metrics.Labels{{Name: "model", Value: "b"}}, Timestamp: fixedTime, Value: 5},
	}

	var buf strings.Builder
	if err := WriteLines(&buf, samples); err != nil {
		t.Fatalf("WriteLines: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("got %d lines, want 2 (one per distinct series)", len(lines))
	}

	var seriesA, seriesB *line
	for _, l := range lines {
		var parsed line
		if err := json.Unmarshal([]byte(l), &parsed); err != nil {
			t.Fatalf("unmarshal line %q: %v", l, err)
		}
		switch parsed.Metric["model"] {
		case "a":
			seriesA = &parsed
		case "b":
			seriesB = &parsed
		}
	}

	if seriesA == nil {
		t.Fatal("series a not found")
	}
	if len(seriesA.Values) != 2 || seriesA.Values[0] != 10 || seriesA.Values[1] != 25 {
		t.Errorf("seriesA.Values = %v, want [10, 25]", seriesA.Values)
	}
	if len(seriesA.Timestamps) != 2 {
		t.Errorf("seriesA.Timestamps has %d entries, want 2", len(seriesA.Timestamps))
	}
	if seriesA.Metric["__name__"] != "aitokens_tokens_total" {
		t.Errorf(`seriesA.Metric["__name__"] = %q, want aitokens_tokens_total`, seriesA.Metric["__name__"])
	}

	if seriesB == nil {
		t.Fatal("series b not found")
	}
	if len(seriesB.Values) != 1 || seriesB.Values[0] != 5 {
		t.Errorf("seriesB.Values = %v, want [5]", seriesB.Values)
	}
}

func TestWriteLines_TimestampsAreUnixMillis(t *testing.T) {
	samples := []metrics.Sample{
		{Metric: "m", Labels: nil, Timestamp: fixedTime, Value: 1},
	}
	var buf strings.Builder
	if err := WriteLines(&buf, samples); err != nil {
		t.Fatalf("WriteLines: %v", err)
	}
	var parsed line
	if err := json.Unmarshal([]byte(strings.TrimSpace(buf.String())), &parsed); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if parsed.Timestamps[0] != fixedTime.UnixMilli() {
		t.Errorf("Timestamps[0] = %d, want %d", parsed.Timestamps[0], fixedTime.UnixMilli())
	}
}

func TestImport_PostsToImportEndpointAndSucceedsOn204(t *testing.T) {
	var gotBody string
	var gotPath string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		body := make([]byte, r.ContentLength)
		_, _ = r.Body.Read(body)
		gotBody = string(body)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	samples := []metrics.Sample{
		{Metric: "aitokens_tokens_total", Labels: metrics.Labels{{Name: "model", Value: "a"}}, Timestamp: fixedTime, Value: 42},
	}
	if err := Import(server.URL, samples); err != nil {
		t.Fatalf("Import: %v", err)
	}
	if gotPath != "/api/v1/import" {
		t.Errorf("path = %q, want /api/v1/import", gotPath)
	}
	if !strings.Contains(gotBody, `"aitokens_tokens_total"`) {
		t.Errorf("request body missing expected metric name, got: %s", gotBody)
	}
}

func TestImport_ReturnsErrorOnNon2xx(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte("bad request detail"))
	}))
	defer server.Close()

	err := Import(server.URL, []metrics.Sample{{Metric: "m", Timestamp: fixedTime, Value: 1}})
	if err == nil {
		t.Fatal("expected an error on 400 response")
	}
	if !strings.Contains(err.Error(), "bad request detail") {
		t.Errorf("error should surface response body, got: %v", err)
	}
}
