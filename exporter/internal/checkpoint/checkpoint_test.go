package checkpoint

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoad_MissingFileReturnsZeroState(t *testing.T) {
	s, err := Load(t.TempDir())
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if s != (State{}) {
		t.Errorf("s = %+v, want zero value", s)
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
	}

	if err := Save(dir, want); err != nil {
		t.Fatalf("Save: %v", err)
	}
	got, err := Load(dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got != want {
		t.Errorf("got = %+v, want %+v", got, want)
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
