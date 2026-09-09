// Package checkpoint persists the ingestor's read cursor into usage.db —
// the last id() consumed per table — so a restart resumes instead of
// reprocessing from scratch or, worse, skipping ahead. Lives entirely in
// the exporter's own directory, never in usage.db: the Go side stays
// strictly read-only against the Python-owned file (see MADR-003).
package checkpoint

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const fileName = "ingest_state.json"

// State is the full checkpoint: one cursor per source table, plus whether
// the one-time historical backfill has run. BackfillCompletedAt is a
// RFC3339 timestamp string, empty until backfill succeeds — the Fase 5
// backfill command refuses to re-run without --force once this is set (see
// cmd/aitokens-exporter's backfill subcommand).
//
// ClaudeCodeFileCursors and CopilotReadSessions replace what used to be two
// SQLite tables in the removed Python side (claude_code_read_cursors,
// copilot_read_sessions) — a per-transcript-file byte offset and a
// per-session "already read" set, respectively. They live here now because
// there's no longer a SQLite writer to own them.
type State struct {
	ClaudeCodeUsageEvents int64  `json:"claude_code_usage_events"`
	TaskCalls             int64  `json:"task_calls"`
	CopilotUsageEvents    int64  `json:"copilot_usage_events"`
	UsageSnapshots        int64  `json:"usage_snapshots"`
	BackfillCompletedAt   string `json:"backfill_completed_at,omitempty"`

	// ClaudeCodeFileCursors maps a transcript file's absolute path to the
	// byte offset already consumed from it — mirrors
	// adapters/claude_code_transcript_reader.py's per-file seek/tell cursor.
	ClaudeCodeFileCursors map[string]int64 `json:"claude_code_file_cursors"`

	// CopilotReadSessions is the set of Copilot session_ids whose
	// session.shutdown event has already been read — mirrors
	// copilot_read_sessions. A session absent from this map (or present with
	// false) is re-checked on the next read, since it may not have shut down
	// yet.
	CopilotReadSessions map[string]bool `json:"copilot_read_sessions"`
}

// Load reads the checkpoint file, returning a zero-valued State (not an
// error) if it doesn't exist yet — the natural state before the first run.
// The two map fields are always non-nil on return (empty if absent from the
// file), so a caller can write into them (e.g. s.ClaudeCodeFileCursors[path]
// = offset) without a nil-map panic.
func Load(dir string) (State, error) {
	data, err := os.ReadFile(filepath.Join(dir, fileName))
	if os.IsNotExist(err) {
		return emptyState(), nil
	}
	if err != nil {
		return State{}, fmt.Errorf("read checkpoint: %w", err)
	}
	s := emptyState()
	if err := json.Unmarshal(data, &s); err != nil {
		return State{}, fmt.Errorf("parse checkpoint: %w", err)
	}
	if s.ClaudeCodeFileCursors == nil {
		s.ClaudeCodeFileCursors = map[string]int64{}
	}
	if s.CopilotReadSessions == nil {
		s.CopilotReadSessions = map[string]bool{}
	}
	return s, nil
}

func emptyState() State {
	return State{
		ClaudeCodeFileCursors: map[string]int64{},
		CopilotReadSessions:   map[string]bool{},
	}
}

// Save writes the checkpoint atomically (write to a temp file, then rename)
// so a crash mid-write never leaves a corrupt or half-written checkpoint —
// the rename is what a reader ever sees, not the partial write.
func Save(dir string, s State) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("mkdir %s: %w", dir, err)
	}
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal checkpoint: %w", err)
	}
	final := filepath.Join(dir, fileName)
	tmp := final + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return fmt.Errorf("write temp checkpoint: %w", err)
	}
	if err := os.Rename(tmp, final); err != nil {
		return fmt.Errorf("rename checkpoint into place: %w", err)
	}
	return nil
}
