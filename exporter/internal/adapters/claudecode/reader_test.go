package claudecode

import (
	"testing"
)

// TestReadNewEvents_ParsesRealTranscriptShape is the seam: given a
// projects directory laid out the way ~/.claude/projects actually is
// (one dir per project, .jsonl transcripts inside), ReadNewEvents returns
// the deduplicated, correctly-typed events a fresh cursor state should see.
// testdata/projects/proj-a/session1.jsonl exercises, in one file:
//   - a duplicate request_id (same assistant response split across content
//     blocks, as real Claude Code transcripts do) — must count once
//   - a custom-title line — must produce a SessionTitle, not an event
//   - a subagent line (isSidechain=true, agentId set) — must carry AgentID
//   - a non-assistant line (type=user) — must be ignored
//   - a malformed JSON line — must be skipped, not fatal
//   - an assistant line with an empty usage object — must be excluded
//     (mirrors the removed Python reader's `if not usage: return None`,
//     since {} is falsy there)
func TestReadNewEvents_ParsesRealTranscriptShape(t *testing.T) {
	reader := NewReader("testdata/projects")

	events, titles, _, err := reader.ReadNewEvents(map[string]int64{})
	if err != nil {
		t.Fatalf("ReadNewEvents: %v", err)
	}

	if len(events) != 2 {
		t.Fatalf("len(events) = %d, want 2 (req-1 deduplicated, req-2 subagent; req-3 excluded for empty usage)", len(events))
	}

	if events[0].RequestID != "req-1" {
		t.Errorf("events[0].RequestID = %q, want req-1", events[0].RequestID)
	}
	if events[0].InputTokens != 100 || events[0].OutputTokens != 50 {
		t.Errorf("events[0] tokens = %d/%d, want 100/50", events[0].InputTokens, events[0].OutputTokens)
	}
	if events[0].AgentID != "" {
		t.Errorf("events[0].AgentID = %q, want empty (main agent)", events[0].AgentID)
	}
	if events[0].ProjectSlug != "proj-a" {
		t.Errorf("events[0].ProjectSlug = %q, want proj-a", events[0].ProjectSlug)
	}

	if events[1].RequestID != "req-2" {
		t.Errorf("events[1].RequestID = %q, want req-2", events[1].RequestID)
	}
	if events[1].AgentID != "a51318970185552cb" {
		t.Errorf("events[1].AgentID = %q, want a51318970185552cb (subagent)", events[1].AgentID)
	}

	if len(titles) != 1 {
		t.Fatalf("len(titles) = %d, want 1", len(titles))
	}
	if titles[0].SessionID != "sess-1" || titles[0].Title != "morning-refactor" {
		t.Errorf("titles[0] = %+v, want {sess-1 morning-refactor}", titles[0])
	}
}

// TestReadNewEvents_DedupsRepeatedCustomTitleLines is the seam for a real
// bug found by comparing Go's output against production data: a session's
// custom-title line is rewritten to the transcript every time Claude Code
// re-saves session state, not written once — real transcripts had the
// same {session_id, title} line repeated thousands of times across the
// account. The removed Python reader never had this problem because
// record_session_title was a SQLite upsert (ON CONFLICT session_id DO
// UPDATE); without a database doing that collapsing, the reader itself
// must deduplicate to one title per session_id (last one wins, since a
// later line in file order is a later save).
func TestReadNewEvents_DedupsRepeatedCustomTitleLines(t *testing.T) {
	reader := NewReader("testdata/repeated-title")

	_, titles, _, err := reader.ReadNewEvents(map[string]int64{})
	if err != nil {
		t.Fatalf("ReadNewEvents: %v", err)
	}

	if len(titles) != 1 {
		t.Fatalf("len(titles) = %d, want 1 (three repeated lines collapse to one)", len(titles))
	}
	if titles[0].SessionID != "sess-x" || titles[0].Title != "renamed-later" {
		t.Errorf("titles[0] = %+v, want {sess-x renamed-later} (last write wins)", titles[0])
	}
}

// TestReadNewEvents_CursorPreventsReprocessing is the seam for the
// incremental-read contract: calling ReadNewEvents again with the cursor
// map it just returned must find nothing new, and calling it with an empty
// cursor map (as if starting fresh) must find everything again — proving
// the returned cursor is what actually gates re-reads, not some hidden
// internal state.
func TestReadNewEvents_CursorPreventsReprocessing(t *testing.T) {
	reader := NewReader("testdata/projects")

	firstEvents, _, cursors, err := reader.ReadNewEvents(map[string]int64{})
	if err != nil {
		t.Fatalf("first ReadNewEvents: %v", err)
	}
	if len(firstEvents) != 2 {
		t.Fatalf("first call: len(events) = %d, want 2", len(firstEvents))
	}

	secondEvents, secondTitles, _, err := reader.ReadNewEvents(cursors)
	if err != nil {
		t.Fatalf("second ReadNewEvents: %v", err)
	}
	if len(secondEvents) != 0 {
		t.Errorf("second call (same cursor): len(events) = %d, want 0 (nothing new)", len(secondEvents))
	}
	if len(secondTitles) != 0 {
		t.Errorf("second call (same cursor): len(titles) = %d, want 0 (nothing new)", len(secondTitles))
	}

	thirdEvents, _, _, err := reader.ReadNewEvents(map[string]int64{})
	if err != nil {
		t.Fatalf("third ReadNewEvents: %v", err)
	}
	if len(thirdEvents) != 2 {
		t.Errorf("third call (fresh cursor): len(events) = %d, want 2 (re-reads from scratch)", len(thirdEvents))
	}
}
