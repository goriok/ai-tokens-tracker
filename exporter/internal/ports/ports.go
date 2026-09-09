// Package ports defines the secondary/driven interfaces the exporter's
// ingest logic depends on — mirrors core/interfaces.py's hexagonal split
// (see the now-removed MADR-002 in Python history, and MADR-004 for the
// Go-side equivalent): TranscriptReader for passive, zero-cost sources
// (local files the CLI already writes) and QuotaRunner for the one
// zero-cost CLI subprocess call (agy's /usage meta-command). Adapters
// implementing these live under internal/adapters/*; ingest depends only
// on these interfaces, never on a concrete adapter type — the same
// discipline the removed Python scripts/ layer followed.
package ports

import (
	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// ClaudeCodeTranscriptReader reads new (not-yet-seen) events from Claude
// Code's local session transcripts, given the caller's current cursor
// state (checkpoint.State.ClaudeCodeFileCursors — a byte offset per
// transcript file). Returns the events found, any newly-seen session
// titles, and the cursor state updated to reflect what was read — callers
// persist that returned state (via checkpoint.Save), not any state the
// reader keeps internally: an in-in/out-out shape, so the caller always
// owns the cursor's source of truth.
type ClaudeCodeTranscriptReader interface {
	ReadNewEvents(cursors map[string]int64) (events []model.ClaudeCodeEvent, titles []model.SessionTitle, newCursors map[string]int64, err error)
}

// CopilotTranscriptReader reads new (not-yet-seen) completed sessions from
// Copilot CLI's local session-state directory, given the set of
// already-read session_ids. A session with no session.shutdown event yet
// is skipped, not an error — it's picked up on a future call once the
// session actually ends. Returns the updated read-set the same way
// ClaudeCodeTranscriptReader returns updated cursors.
type CopilotTranscriptReader interface {
	ReadNewEvents(readSessions map[string]bool) (events []model.CopilotEvent, titles []model.SessionTitle, newReadSessions map[string]bool, err error)
}

// QuotaRunner fetches agy's weekly quota snapshot via the zero-cost
// `/usage` meta-command (usage.total_tokens: 0 in agy's own response) — see
// MADR-001 in the removed Python docs/madrs/ for why this, not task-call
// usage, is the primary quota signal.
type QuotaRunner interface {
	FetchQuota() ([]model.UsageSnapshot, error)
}
