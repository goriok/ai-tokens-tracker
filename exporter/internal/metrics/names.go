// Package metrics maps the domain events read by sqlitesource into
// Prometheus series: label sets, and monotonic counter values via an
// in-memory accumulator. See docs/madrs/MADR-003 for the label cardinality
// rationale — this package is the enforcement point for it.
package metrics

import (
	"regexp"
	"strings"
)

// Metric names — Prometheus naming convention: _total suffix on counters,
// unit made explicit where not a bare count.
const (
	TokensTotal           = "aitokens_tokens_total"
	QuotaRemainingRatio   = "aitokens_quota_remaining_ratio"
	CacheCreationMeasured = "aitokens_cache_creation_measured"
	IngestLastID          = "aitokens_ingest_last_id"
	IngestEventsTotal     = "aitokens_ingest_events_total"
	IngestTooOldTotal     = "aitokens_ingest_too_old_total"
)

// TokenType label values — one counter with a token_type label, not four
// separate metrics: all four are the same unit (tokens) and the common
// query ("total spent") is sum(...) over the label, not four metric names
// the caller has to remember to add up.
const (
	TokenTypeInput         = "input"
	TokenTypeOutput        = "output"
	TokenTypeCacheRead     = "cache_read"
	TokenTypeCacheCreation = "cache_creation"
)

// AgentKind label values — replaces the raw agent_id (524 distinct values
// measured) with the two-value distinction that's actually analytically
// useful: was this a subagent call or not.
const (
	AgentKindMain = "main"
	AgentKindSub  = "sub"
)

// AgentKind derives the low-cardinality label from the raw agent_id field
// (empty/NULL means the main agent — see adapters/claude_code_transcript_reader.py,
// isSidechain is only set for subagent events).
func AgentKind(agentID string) string {
	if agentID == "" {
		return AgentKindMain
	}
	return AgentKindSub
}

var slugNonAlnum = regexp.MustCompile(`[^a-z0-9]+`)

// SlugifyModelGroup turns agy's quota model_group ("Gemini Models", "Claude
// and GPT models") into a PromQL-friendly label value. The display form
// isn't kept as a second label — a slug is enough to identify the group,
// and adding model_group_display would double every quota series for no
// query anyone has asked for.
func SlugifyModelGroup(group string) string {
	slug := slugNonAlnum.ReplaceAllString(strings.ToLower(group), "_")
	return strings.Trim(slug, "_")
}
