// Package model mirrors the Python domain types in core/model.py — the Go
// exporter reads the same SQLite tables the Python side writes, so these
// types need to stay in lockstep with the schema in adapters/sqlite_usage_store.py.
package model

import "time"

// ClaudeCodeEvent is one row of claude_code_usage_events.
type ClaudeCodeEvent struct {
	ID                       int64
	Timestamp                time.Time
	SessionID                string
	ProjectSlug              string
	Cwd                      string
	GitBranch                string
	Model                    string
	RequestID                string
	InputTokens              int64
	OutputTokens             int64
	CacheReadInputTokens     int64
	CacheCreationInputTokens int64
	AgentID                  string // empty when NULL — subagent events only
}

// CopilotEvent is one row of copilot_usage_events — one whole session,
// timestamped at session start (see MADR-003: known coarse granularity).
type CopilotEvent struct {
	ID                  int64
	Timestamp           time.Time
	SessionID           string
	Cwd                 string
	Model               string
	InputTokens         int64
	OutputTokens        int64
	CacheReadTokens     int64
	CacheCreationTokens int64
}

// TaskCall is one row of task_calls — a tracked -p invocation (agy or copilot).
type TaskCall struct {
	ID                  int64
	Timestamp           time.Time
	Model               string
	Status              string
	InputTokens         int64
	OutputTokens        int64
	ThinkingTokens      int64
	TotalTokens         int64
	DurationS           float64
	Task                string
	CacheReadTokens     int64
	Source              string
	CacheCreationTokens int64
	ConfidenceScore     *float64
}

// CacheCreationMeasured mirrors core/model.py's UsageEvent.cache_creation_measured:
// false only for source=="agy", whose CLI output has no cache-write field at
// all — 0 there means "unmeasured", not "confirmed zero".
func (t TaskCall) CacheCreationMeasured() bool {
	return t.Source != "agy"
}

// UsageSnapshot is one row of usage_snapshots — agy's weekly quota poll.
// A fraction-remaining metric, not a token count — kept separate from the
// token series (see core/usage.py's build_dashboard_payload docstring).
type UsageSnapshot struct {
	ID                int64
	Timestamp         time.Time
	ModelGroup        string
	RemainingFraction float64
	ResetTime         string
}
