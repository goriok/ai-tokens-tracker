package metrics

import (
	"sort"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// Labels is an ordered set of Prometheus label name/value pairs. Kept as a
// slice (not a map) so two Labels with the same content always produce the
// same series key — order matters for that, map iteration order doesn't.
type Labels []Label

type Label struct {
	Name  string
	Value string
}

// Key returns a stable string identity for this label set, suitable as a
// map key for the accumulator. Labels are sorted by name first so the same
// logical series always yields the same key regardless of construction order.
func (l Labels) Key() string {
	sorted := make(Labels, len(l))
	copy(sorted, l)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Name < sorted[j].Name })
	var buf []byte
	for _, lbl := range sorted {
		buf = append(buf, lbl.Name...)
		buf = append(buf, '=')
		buf = append(buf, lbl.Value...)
		buf = append(buf, ';')
	}
	return string(buf)
}

// RawSample is one (metric, labels, timestamp, delta) tuple derived from a
// single source event — "delta" because token counts here are the amount
// this one event contributed, not yet the running total. The accumulator
// turns a stream of RawSamples into monotonic counter Samples.
type RawSample struct {
	Metric    string
	Labels    Labels
	Timestamp time.Time
	Delta     float64
}

// ClaudeCodeSamples maps one Claude Code event into up to 4 raw token
// samples (one per token_type actually present — zero-valued dimensions
// still get a sample, so the series exists and rate()/increase() over it
// isn't sparse) plus nothing else: Claude Code always measures all 4
// dimensions, so no CacheCreationMeasured gauge sample is needed here.
func ClaudeCodeSamples(e model.ClaudeCodeEvent) []RawSample {
	base := Labels{
		{Name: "source", Value: "claude-code"},
		{Name: "model", Value: e.Model},
		{Name: "project", Value: e.ProjectSlug},
		{Name: "git_branch", Value: e.GitBranch},
		{Name: "agent_kind", Value: AgentKind(e.AgentID)},
	}
	return tokenSamples(base, e.Timestamp, e.InputTokens, e.OutputTokens, e.CacheReadInputTokens, e.CacheCreationInputTokens)
}

// CopilotSamples maps one Copilot session-aggregate event into token
// samples. The timestamp is the session's startTime, not per-request — see
// MADR-003's documented granularity limitation; not corrected here.
func CopilotSamples(e model.CopilotEvent) []RawSample {
	base := Labels{
		{Name: "source", Value: "copilot"},
		{Name: "model", Value: e.Model},
		{Name: "project", Value: e.Cwd},
		{Name: "git_branch", Value: ""},
		{Name: "agent_kind", Value: AgentKindMain},
	}
	return tokenSamples(base, e.Timestamp, e.InputTokens, e.OutputTokens, e.CacheReadTokens, e.CacheCreationTokens)
}

// TaskCallSamples maps one tracked -p call (agy or copilot-track) into token
// samples. source comes from the call itself (TaskCall.Source), not a
// literal — task_calls covers more than one tool.
func TaskCallSamples(c model.TaskCall) []RawSample {
	base := Labels{
		{Name: "source", Value: c.Source},
		{Name: "model", Value: c.Model},
		{Name: "project", Value: ""},
		{Name: "git_branch", Value: ""},
		{Name: "agent_kind", Value: AgentKindMain},
	}
	samples := tokenSamples(base, c.Timestamp, c.InputTokens, c.OutputTokens, c.CacheReadTokens, c.CacheCreationTokens)

	// agy's CLI output has no cache-write field at all — record whether this
	// source's cache_creation dimension is genuinely measured, so a 0 from
	// agy never silently reads as "confirmed zero" against sources that do
	// measure it (see core/model.py's cache_creation_measured docstring).
	measured := 0.0
	if c.CacheCreationMeasured() {
		measured = 1.0
	}
	samples = append(samples, RawSample{
		Metric:    CacheCreationMeasured,
		Labels:    Labels{{Name: "source", Value: c.Source}},
		Timestamp: c.Timestamp,
		Delta:     measured, // gauge value, not an accumulated delta — see accumulator.go
	})
	return samples
}

// UsageSnapshotSample maps one agy quota poll into a gauge sample. A
// fraction-remaining metric, not a token count — kept out of TokensTotal
// entirely, mirroring core/usage.py's build_dashboard_payload docstring on
// why UsageSnapshot can't be folded into UsageEvent without losing meaning.
func UsageSnapshotSample(s model.UsageSnapshot) RawSample {
	return RawSample{
		Metric: QuotaRemainingRatio,
		Labels: Labels{
			{Name: "model_group", Value: SlugifyModelGroup(s.ModelGroup)},
		},
		Timestamp: s.Timestamp,
		Delta:     s.RemainingFraction, // gauge value — see accumulator.go
	}
}

func tokenSamples(base Labels, ts time.Time, input, output, cacheRead, cacheCreation int64) []RawSample {
	dims := []struct {
		tokenType string
		value     int64
	}{
		{TokenTypeInput, input},
		{TokenTypeOutput, output},
		{TokenTypeCacheRead, cacheRead},
		{TokenTypeCacheCreation, cacheCreation},
	}
	samples := make([]RawSample, 0, len(dims))
	for _, d := range dims {
		labels := append(append(Labels{}, base...), Label{Name: "token_type", Value: d.tokenType})
		samples = append(samples, RawSample{
			Metric:    TokensTotal,
			Labels:    labels,
			Timestamp: ts,
			Delta:     float64(d.value),
		})
	}
	return samples
}
