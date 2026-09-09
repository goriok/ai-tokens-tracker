package metrics

import (
	"testing"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

var fixedTime = time.Date(2026, 9, 9, 12, 0, 0, 0, time.UTC)

// labelNames collects the set of label names present across a batch of raw
// samples — used to assert high-cardinality fields never become labels.
func labelNames(samples []RawSample) map[string]bool {
	names := map[string]bool{}
	for _, s := range samples {
		for _, l := range s.Labels {
			names[l.Name] = true
		}
	}
	return names
}

func TestClaudeCodeSamples_NeverLabelsHighCardinalityFields(t *testing.T) {
	// session_id (267 distinct values measured), agent_id (524), and
	// request_id (22,387) must never appear as label names — that's the
	// exact anti-pattern that would blow up series cardinality. agent_kind
	// (2 values) is the low-cardinality substitute for agent_id.
	e := model.ClaudeCodeEvent{
		Timestamp:    fixedTime,
		SessionID:    "sess-1",
		ProjectSlug:  "proj-a",
		Model:        "claude-sonnet-5",
		RequestID:    "req-1",
		AgentID:      "agent-xyz",
		InputTokens:  1,
		OutputTokens: 1,
	}
	names := labelNames(ClaudeCodeSamples(e, "my-session"))

	for _, forbidden := range []string{"session_id", "agent_id", "request_id"} {
		if names[forbidden] {
			t.Errorf("label set must not include %q (high cardinality), got %v", forbidden, names)
		}
	}
	for _, required := range []string{"source", "model", "project", "git_branch", "agent_kind", "token_type", "session_name"} {
		if !names[required] {
			t.Errorf("label set missing %q, got %v", required, names)
		}
	}
}

func TestClaudeCodeSamples_SessionNameLabelReflectsArgument(t *testing.T) {
	// session_name is opt-in and bounded by how often someone names a run
	// (unlike session_id/agent_id) — see MADR-003. Empty when unnamed, the
	// common case.
	e := model.ClaudeCodeEvent{Timestamp: fixedTime, Model: "m", ProjectSlug: "p"}

	unnamed := ClaudeCodeSamples(e, "")
	if got := labelValue(unnamed[0].Labels, "session_name"); got != "" {
		t.Errorf("unnamed session_name = %q, want empty", got)
	}

	named := ClaudeCodeSamples(e, "morning-refactor")
	if got := labelValue(named[0].Labels, "session_name"); got != "morning-refactor" {
		t.Errorf("named session_name = %q, want morning-refactor", got)
	}
}

func TestClaudeCodeSamples_FourTokenTypesEachEvent(t *testing.T) {
	e := model.ClaudeCodeEvent{
		Timestamp:                fixedTime,
		Model:                    "claude-sonnet-5",
		ProjectSlug:              "proj-a",
		InputTokens:              100,
		OutputTokens:             50,
		CacheReadInputTokens:     10,
		CacheCreationInputTokens: 5,
	}
	samples := ClaudeCodeSamples(e, "")
	if len(samples) != 4 {
		t.Fatalf("len(samples) = %d, want 4 (one per token_type)", len(samples))
	}

	want := map[string]float64{
		TokenTypeInput:         100,
		TokenTypeOutput:        50,
		TokenTypeCacheRead:     10,
		TokenTypeCacheCreation: 5,
	}
	for _, s := range samples {
		if s.Metric != TokensTotal {
			t.Errorf("Metric = %q, want %q", s.Metric, TokensTotal)
		}
		var tokenType string
		for _, l := range s.Labels {
			if l.Name == "token_type" {
				tokenType = l.Value
			}
		}
		wantDelta, ok := want[tokenType]
		if !ok {
			t.Fatalf("unexpected token_type %q", tokenType)
		}
		if s.Delta != wantDelta {
			t.Errorf("token_type=%q Delta = %v, want %v", tokenType, s.Delta, wantDelta)
		}
	}
}

func TestClaudeCodeSamples_AgentKindReflectsSubagent(t *testing.T) {
	main := ClaudeCodeSamples(model.ClaudeCodeEvent{Timestamp: fixedTime, Model: "m", ProjectSlug: "p"}, "")
	sub := ClaudeCodeSamples(model.ClaudeCodeEvent{Timestamp: fixedTime, Model: "m", ProjectSlug: "p", AgentID: "agent-1"}, "")

	if got := labelValue(main[0].Labels, "agent_kind"); got != AgentKindMain {
		t.Errorf("main event agent_kind = %q, want %q", got, AgentKindMain)
	}
	if got := labelValue(sub[0].Labels, "agent_kind"); got != AgentKindSub {
		t.Errorf("subagent event agent_kind = %q, want %q", got, AgentKindSub)
	}
}

func TestTaskCallSamples_EmitsCacheCreationMeasuredGauge(t *testing.T) {
	tests := []struct {
		source string
		want   float64
	}{
		{"agy", 0},     // agy's CLI has no cache-write field — unmeasured
		{"copilot", 1}, // Copilot genuinely reports it
	}
	for _, tt := range tests {
		call := model.TaskCall{Timestamp: fixedTime, Model: "m", Source: tt.source}
		samples := TaskCallSamples(call)

		var found bool
		for _, s := range samples {
			if s.Metric != CacheCreationMeasured {
				continue
			}
			found = true
			if s.Delta != tt.want {
				t.Errorf("source=%q CacheCreationMeasured Delta = %v, want %v", tt.source, s.Delta, tt.want)
			}
		}
		if !found {
			t.Errorf("source=%q: no %s sample emitted", tt.source, CacheCreationMeasured)
		}
	}
}

func TestUsageSnapshotSample_IsGaugeNotTokenMetric(t *testing.T) {
	snap := model.UsageSnapshot{Timestamp: fixedTime, ModelGroup: "Gemini Models", RemainingFraction: 0.42}
	sample := UsageSnapshotSample(snap)

	if sample.Metric != QuotaRemainingRatio {
		t.Errorf("Metric = %q, want %q", sample.Metric, QuotaRemainingRatio)
	}
	if sample.Delta != 0.42 {
		t.Errorf("Delta = %v, want 0.42", sample.Delta)
	}
	if got := labelValue(sample.Labels, "model_group"); got != "gemini_models" {
		t.Errorf("model_group label = %q, want gemini_models", got)
	}
}

func TestCopilotSamples_GranularityIsSessionLevel(t *testing.T) {
	// Documents the known limitation (MADR-003): Copilot's timestamp is the
	// session start, not per-request — this test just pins that the sample
	// carries the event's timestamp unchanged, not something finer-grained
	// that doesn't exist in the source data.
	e := model.CopilotEvent{Timestamp: fixedTime, Model: "gpt-5.6-sol", InputTokens: 10}
	samples := CopilotSamples(e)
	for _, s := range samples {
		if !s.Timestamp.Equal(fixedTime) {
			t.Errorf("Timestamp = %v, want %v", s.Timestamp, fixedTime)
		}
	}
}

func labelValue(labels Labels, name string) string {
	for _, l := range labels {
		if l.Name == name {
			return l.Value
		}
	}
	return ""
}
