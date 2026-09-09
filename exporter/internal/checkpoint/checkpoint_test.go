package checkpoint

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestLoad_MissingFileReturnsZeroState(t *testing.T) {
	s, err := Load(t.TempDir())
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if s.ClaudeCodeUsageEvents != 0 || s.TaskCalls != 0 || s.CopilotUsageEvents != 0 ||
		s.UsageSnapshots != 0 || s.BackfillCompletedAt != "" {
		t.Errorf("s = %+v, want all scalar fields zero", s)
	}
}

func TestSaveThenLoad_Roundtrips(t *testing.T) {
	dir := t.TempDir()
	want := State{
		ClaudeCodeUsageEvents: 23733,
		TaskCalls:             118,
		CopilotUsageEvents:    29,
		UsageSnapshots:        44,
		BackfillCompletedAt:   "2026-09-09T18:00:00Z",
		ClaudeCodeFileCursors: map[string]int64{},
		CopilotReadSessions:   map[string]bool{},
	}

	if err := Save(dir, want); err != nil {
		t.Fatalf("Save: %v", err)
	}
	got, err := Load(dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got = %+v, want %+v", got, want)
	}
}

// TestSaveThenLoad_RoundtripsFileCursors is the seam for the ex-Python
// per-file byte-offset cursor (claude_code_read_cursors table) and the
// per-session "already read" set (copilot_read_sessions table) — both now
// live in this same checkpoint file instead of usage.db, since there's no
// SQLite writer left to own them.
func TestSaveThenLoad_RoundtripsFileCursors(t *testing.T) {
	dir := t.TempDir()
	want := State{
		ClaudeCodeFileCursors: map[string]int64{
			"/home/user/.claude/projects/proj-a/session1.jsonl": 4096,
			"/home/user/.claude/projects/proj-b/session2.jsonl": 0,
		},
		CopilotReadSessions: map[string]bool{
			"0982ac68-0383-4a91-a51c-3f36641fd691": true,
		},
	}

	if err := Save(dir, want); err != nil {
		t.Fatalf("Save: %v", err)
	}
	got, err := Load(dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got = %+v, want %+v", got, want)
	}
}

// TestLoad_MissingFileReturnsUsableMaps ensures the zero-value State from a
// fresh checkpoint has non-nil maps ready to write into — a caller doing
// `s.ClaudeCodeFileCursors[path] = offset` on a nil map would panic.
func TestLoad_MissingFileReturnsUsableMaps(t *testing.T) {
	s, err := Load(t.TempDir())
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if s.ClaudeCodeFileCursors == nil {
		t.Error("ClaudeCodeFileCursors is nil, want an empty initialized map")
	}
	if s.CopilotReadSessions == nil {
		t.Error("CopilotReadSessions is nil, want an empty initialized map")
	}
}

func TestSave_OverwritesPreviousState(t *testing.T) {
	dir := t.TempDir()
	if err := Save(dir, State{ClaudeCodeUsageEvents: 100}); err != nil {
		t.Fatalf("Save 1: %v", err)
	}
	if err := Save(dir, State{ClaudeCodeUsageEvents: 200}); err != nil {
		t.Fatalf("Save 2: %v", err)
	}
	got, err := Load(dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.ClaudeCodeUsageEvents != 200 {
		t.Errorf("ClaudeCodeUsageEvents = %d, want 200 (latest save wins)", got.ClaudeCodeUsageEvents)
	}
}

func TestSave_LeavesNoTempFileBehind(t *testing.T) {
	dir := t.TempDir()
	if err := Save(dir, State{ClaudeCodeUsageEvents: 1}); err != nil {
		t.Fatalf("Save: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dir, fileName+".tmp")); !os.IsNotExist(err) {
		t.Errorf("expected no leftover .tmp file, stat err = %v", err)
	}
}
