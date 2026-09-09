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
type State struct {
	ClaudeCodeUsageEvents int64  `json:"claude_code_usage_events"`
	TaskCalls             int64  `json:"task_calls"`
	CopilotUsageEvents    int64  `json:"copilot_usage_events"`
	UsageSnapshots        int64  `json:"usage_snapshots"`
	BackfillCompletedAt   string `json:"backfill_completed_at,omitempty"`
}

// Load reads the checkpoint file, returning a zero-valued State (not an
// error) if it doesn't exist yet — the natural state before the first run.
func Load(dir string) (State, error) {
	data, err := os.ReadFile(filepath.Join(dir, fileName))
	if os.IsNotExist(err) {
		return State{}, nil
	}
	if err != nil {
		return State{}, fmt.Errorf("read checkpoint: %w", err)
	}
	var s State
	if err := json.Unmarshal(data, &s); err != nil {
		return State{}, fmt.Errorf("parse checkpoint: %w", err)
	}
	return s, nil
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
