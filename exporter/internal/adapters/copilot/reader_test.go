package copilot

import (
	"testing"
)

// TestReadNewEvents_ReadsCompletedSessionsOnly is the seam: given a
// session-state directory shaped like ~/.copilot/session-state (one
// subdirectory per session_id, events.jsonl + optional workspace.yaml
// inside), ReadNewEvents returns one CopilotEvent per session that has a
// session.shutdown event — a session still running (no shutdown yet, like
// sess-no-shutdown) must be silently skipped, not an error, since it'll be
// picked up on a future read once it actually ends.
func TestReadNewEvents_ReadsCompletedSessionsOnly(t *testing.T) {
	reader := NewReader("testdata/session-state")

	events, titles, _, err := reader.ReadNewEvents(map[string]bool{})
	if err != nil {
		t.Fatalf("ReadNewEvents: %v", err)
	}

	// 3 session dirs on disk, but only 2 have a session.shutdown.
	if len(events) != 2 {
		t.Fatalf("len(events) = %d, want 2 (sess-no-shutdown excluded)", len(events))
	}

	var byID = map[string]int{}
	for i, e := range events {
		byID[e.SessionID] = i
	}
	if _, ok := byID["sess-no-shutdown"]; ok {
		t.Error("sess-no-shutdown must not appear — it has no session.shutdown event")
	}

	got := events[byID["sess-shutdown-1"]]
	if got.Model != "gpt-5.6-sol" {
		t.Errorf("Model = %q, want gpt-5.6-sol", got.Model)
	}
	if got.InputTokens != 300 || got.OutputTokens != 120 || got.CacheReadTokens != 20 || got.CacheCreationTokens != 15 {
		t.Errorf("tokens = %d/%d/%d/%d, want 300/120/20/15",
			got.InputTokens, got.OutputTokens, got.CacheReadTokens, got.CacheCreationTokens)
	}
	if got.Cwd != "/home/user/proj-c" {
		t.Errorf("Cwd = %q, want /home/user/proj-c", got.Cwd)
	}

	if len(titles) != 1 {
		t.Fatalf("len(titles) = %d, want 1 (only sess-named has a workspace.yaml name)", len(titles))
	}
	if titles[0].SessionID != "sess-named" || titles[0].Title != "my-named-experiment" {
		t.Errorf("titles[0] = %+v, want {sess-named my-named-experiment}", titles[0])
	}
}
