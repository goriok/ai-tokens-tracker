package sqlitesource

import (
	"testing"
)

const fixturePath = "testdata/fixture.db"

func openFixture(t *testing.T) *Source {
	t.Helper()
	s, err := Open(fixturePath)
	if err != nil {
		t.Fatalf("open fixture: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func TestClaudeCodeEventsSince(t *testing.T) {
	s := openFixture(t)

	events, maxID, badRows, err := s.ClaudeCodeEventsSince(0)
	if err != nil {
		t.Fatalf("ClaudeCodeEventsSince: %v", err)
	}
	if badRows != 0 {
		t.Errorf("badRows = %d, want 0", badRows)
	}
	if len(events) != 3 {
		t.Fatalf("len(events) = %d, want 3", len(events))
	}
	if maxID != 3 {
		t.Errorf("maxID = %d, want 3", maxID)
	}

	// Rows come back in id order (arrival order), not timestamp order — the
	// fixture's 3rd row is a "late discovery" with an earlier timestamp than
	// the other two, proving the cursor must not sort by timestamp.
	if events[2].RequestID != "req-3-late-discovery" {
		t.Errorf("events[2].RequestID = %q, want req-3-late-discovery", events[2].RequestID)
	}
	if !events[2].Timestamp.Before(events[0].Timestamp) {
		t.Errorf("expected the late-discovery row's timestamp to precede row 1's, got %v vs %v",
			events[2].Timestamp, events[0].Timestamp)
	}

	// Subagent row carries agent_id; main-agent rows don't.
	if events[0].AgentID != "" {
		t.Errorf("events[0].AgentID = %q, want empty (main agent)", events[0].AgentID)
	}
	if events[1].AgentID != "agent-xyz" {
		t.Errorf("events[1].AgentID = %q, want agent-xyz", events[1].AgentID)
	}

	// cwd/git_branch NULL in the fixture's 3rd row must not panic and must
	// come back empty, not "<nil>".
	if events[2].Cwd != "" || events[2].GitBranch != "" {
		t.Errorf("events[2] Cwd/GitBranch = %q/%q, want empty", events[2].Cwd, events[2].GitBranch)
	}

	// Cursor semantics: asking again with the new maxID returns nothing new.
	next, _, _, err := s.ClaudeCodeEventsSince(maxID)
	if err != nil {
		t.Fatalf("ClaudeCodeEventsSince(maxID): %v", err)
	}
	if len(next) != 0 {
		t.Errorf("len(next) = %d, want 0 (cursor should not replay ingested rows)", len(next))
	}

	// Partial cursor: only rows after id=1 come back.
	partial, _, _, err := s.ClaudeCodeEventsSince(1)
	if err != nil {
		t.Fatalf("ClaudeCodeEventsSince(1): %v", err)
	}
	if len(partial) != 2 {
		t.Errorf("len(partial) = %d, want 2", len(partial))
	}
}

func TestCopilotEventsSince(t *testing.T) {
	s := openFixture(t)

	events, maxID, badRows, err := s.CopilotEventsSince(0)
	if err != nil {
		t.Fatalf("CopilotEventsSince: %v", err)
	}
	if badRows != 0 {
		t.Errorf("badRows = %d, want 0", badRows)
	}
	if len(events) != 1 {
		t.Fatalf("len(events) = %d, want 1", len(events))
	}
	if maxID != 1 {
		t.Errorf("maxID = %d, want 1", maxID)
	}
	if events[0].SessionID != "copilot-sess-1" {
		t.Errorf("SessionID = %q, want copilot-sess-1", events[0].SessionID)
	}
}

func TestTaskCallsSince(t *testing.T) {
	s := openFixture(t)

	calls, maxID, badRows, err := s.TaskCallsSince(0)
	if err != nil {
		t.Fatalf("TaskCallsSince: %v", err)
	}
	if badRows != 0 {
		t.Errorf("badRows = %d, want 0", badRows)
	}
	if len(calls) != 2 {
		t.Fatalf("len(calls) = %d, want 2", len(calls))
	}
	if maxID != 2 {
		t.Errorf("maxID = %d, want 2", maxID)
	}

	// First call has no confidence score (NULL); second does.
	if calls[0].ConfidenceScore != nil {
		t.Errorf("calls[0].ConfidenceScore = %v, want nil", calls[0].ConfidenceScore)
	}
	if calls[1].ConfidenceScore == nil || *calls[1].ConfidenceScore != 8.5 {
		t.Errorf("calls[1].ConfidenceScore = %v, want 8.5", calls[1].ConfidenceScore)
	}

	// source drives CacheCreationMeasured — agy is unmeasured, copilot is measured.
	if calls[0].Source != "agy" || calls[0].CacheCreationMeasured() {
		t.Errorf("calls[0] Source=%q CacheCreationMeasured()=%v, want agy/false",
			calls[0].Source, calls[0].CacheCreationMeasured())
	}
	if calls[1].Source != "copilot" || !calls[1].CacheCreationMeasured() {
		t.Errorf("calls[1] Source=%q CacheCreationMeasured()=%v, want copilot/true",
			calls[1].Source, calls[1].CacheCreationMeasured())
	}
}

func TestUsageSnapshotsSince(t *testing.T) {
	s := openFixture(t)

	snapshots, maxID, badRows, err := s.UsageSnapshotsSince(0)
	if err != nil {
		t.Fatalf("UsageSnapshotsSince: %v", err)
	}
	if badRows != 0 {
		t.Errorf("badRows = %d, want 0", badRows)
	}
	if len(snapshots) != 1 {
		t.Fatalf("len(snapshots) = %d, want 1", len(snapshots))
	}
	if maxID != 1 {
		t.Errorf("maxID = %d, want 1", maxID)
	}
	if snapshots[0].ModelGroup != "gpt-5" {
		t.Errorf("ModelGroup = %q, want gpt-5", snapshots[0].ModelGroup)
	}
	if snapshots[0].RemainingFraction != 0.42 {
		t.Errorf("RemainingFraction = %v, want 0.42", snapshots[0].RemainingFraction)
	}
}

func TestOpen_ReadOnly_RejectsMissingFile(t *testing.T) {
	// mode=ro against a nonexistent file must fail at Ping, not silently
	// create an empty database (the default rwc mode would).
	_, err := Open("testdata/does-not-exist.db")
	if err == nil {
		t.Fatal("expected error opening a nonexistent db read-only, got nil")
	}
}
