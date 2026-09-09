// Package claudecode implements ports.ClaudeCodeTranscriptReader by reading
// Claude Code's local session transcripts directly — a Go port of the
// removed Python adapters/claude_code_transcript_reader.py, now that
// nothing SQLite-backed remains to read them for us. Zero-cost: these are
// files Claude Code already writes locally, no API call involved.
package claudecode

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// Reader reads .jsonl transcripts under a projects directory shaped like
// ~/.claude/projects: one subdirectory per project, transcripts (including
// subagents/**/*.jsonl) inside.
type Reader struct {
	projectsDir string
}

func NewReader(projectsDir string) *Reader {
	return &Reader{projectsDir: projectsDir}
}

// line is the subset of a transcript JSONL line's fields this reader uses —
// covers both assistant-response lines (type=assistant) and
// custom-title lines (type=custom-title), since a single decode has to
// discriminate between them the way the removed Python reader's two
// separate parse functions did.
type line struct {
	Type        string `json:"type"`
	Timestamp   string `json:"timestamp"`
	SessionID   string `json:"sessionId"`
	Cwd         string `json:"cwd"`
	GitBranch   string `json:"gitBranch"`
	RequestID   string `json:"requestId"`
	IsSidechain bool   `json:"isSidechain"`
	AgentID     string `json:"agentId"`
	CustomTitle string `json:"customTitle"`
	Message     *struct {
		Model string `json:"model"`
		Usage *struct {
			InputTokens              int64 `json:"input_tokens"`
			OutputTokens             int64 `json:"output_tokens"`
			CacheReadInputTokens     int64 `json:"cache_read_input_tokens"`
			CacheCreationInputTokens int64 `json:"cache_creation_input_tokens"`
		} `json:"usage"`
	} `json:"message"`
}

// hasUsage reports whether the line's usage object is present and
// non-empty — mirrors the removed Python reader's `if not usage: return
// None` (an empty {} there is falsy, so it's excluded, same as a missing
// usage key).
func (l line) hasUsage() bool {
	if l.Message == nil || l.Message.Usage == nil {
		return false
	}
	u := l.Message.Usage
	return u.InputTokens != 0 || u.OutputTokens != 0 || u.CacheReadInputTokens != 0 || u.CacheCreationInputTokens != 0
}

func (r *Reader) ReadNewEvents(cursors map[string]int64) ([]model.ClaudeCodeEvent, []model.SessionTitle, map[string]int64, error) {
	newCursors := make(map[string]int64, len(cursors))
	for k, v := range cursors {
		newCursors[k] = v
	}

	var events []model.ClaudeCodeEvent
	var titles []model.SessionTitle

	info, err := os.Stat(r.projectsDir)
	if err != nil || !info.IsDir() {
		return events, titles, newCursors, nil // no projects dir yet is not an error — nothing to read
	}

	projectDirs, err := os.ReadDir(r.projectsDir)
	if err != nil {
		return nil, nil, cursors, fmt.Errorf("read projects dir %s: %w", r.projectsDir, err)
	}
	sort.Slice(projectDirs, func(i, j int) bool { return projectDirs[i].Name() < projectDirs[j].Name() })

	for _, projectDir := range projectDirs {
		if !projectDir.IsDir() {
			continue
		}
		projectSlug := projectDir.Name()
		transcripts, err := findTranscripts(filepath.Join(r.projectsDir, projectSlug))
		if err != nil {
			return nil, nil, cursors, fmt.Errorf("walk project %s: %w", projectSlug, err)
		}
		for _, path := range transcripts {
			fileEvents, fileTitles, newOffset, err := readNewEventsFromFile(projectSlug, path, newCursors[path])
			if err != nil {
				return nil, nil, cursors, fmt.Errorf("read %s: %w", path, err)
			}
			events = append(events, fileEvents...)
			titles = append(titles, fileTitles...)
			newCursors[path] = newOffset
		}
	}

	return events, dedupTitles(titles), newCursors, nil
}

// dedupTitles collapses repeated {session_id, title} lines to one per
// session_id, keeping the last one seen (in the order titles were
// accumulated: file order within a project, project order alphabetical —
// a later occurrence is a later save of that session's title). Necessary
// because Claude Code rewrites the custom-title line to a transcript every
// time it re-saves session state, not once — the removed Python reader
// never needed this, since its SQLite write was an upsert
// (ON CONFLICT session_id DO UPDATE) that collapsed duplicates for free.
func dedupTitles(titles []model.SessionTitle) []model.SessionTitle {
	bySession := make(map[string]model.SessionTitle, len(titles))
	order := make([]string, 0, len(titles))
	for _, t := range titles {
		if _, seen := bySession[t.SessionID]; !seen {
			order = append(order, t.SessionID)
		}
		bySession[t.SessionID] = t // last write wins
	}
	deduped := make([]model.SessionTitle, 0, len(order))
	for _, sessionID := range order {
		deduped = append(deduped, bySession[sessionID])
	}
	return deduped
}

// findTranscripts walks dir recursively for *.jsonl files (includes
// subagents/**/*.jsonl, same as the removed Python reader's rglob), sorted
// for deterministic read order.
func findTranscripts(dir string) ([]string, error) {
	var paths []string
	err := filepath.WalkDir(dir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() && filepath.Ext(path) == ".jsonl" {
			paths = append(paths, path)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Strings(paths)
	return paths, nil
}

func readNewEventsFromFile(projectSlug, path string, offset int64) ([]model.ClaudeCodeEvent, []model.SessionTitle, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, nil, offset, err
	}
	defer f.Close()

	if _, err := f.Seek(offset, 0); err != nil {
		return nil, nil, offset, fmt.Errorf("seek to offset %d: %w", offset, err)
	}

	var events []model.ClaudeCodeEvent
	var titles []model.SessionTitle
	seenRequestIDs := make(map[string]bool)

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 8*1024*1024) // transcript lines can carry large thinking blocks
	var bytesRead int64 = offset
	for scanner.Scan() {
		raw := scanner.Bytes()
		bytesRead += int64(len(raw)) + 1 // +1 for the newline the scanner strips

		var l line
		if err := json.Unmarshal(raw, &l); err != nil {
			log.Printf("skipping malformed claude-code transcript line in %s: %v", path, err)
			continue
		}

		if l.Type == "custom-title" {
			if l.SessionID != "" && l.CustomTitle != "" {
				titles = append(titles, model.SessionTitle{SessionID: l.SessionID, Title: l.CustomTitle})
			}
			continue
		}
		if l.Type != "assistant" {
			continue
		}
		if l.RequestID == "" || seenRequestIDs[l.RequestID] {
			continue
		}
		if !l.hasUsage() {
			continue
		}
		seenRequestIDs[l.RequestID] = true

		ts, err := model.ParseTimestamp(l.Timestamp)
		if err != nil {
			log.Printf("skipping claude-code transcript line with unparseable timestamp in %s: %v", path, err)
			continue
		}

		agentID := ""
		if l.IsSidechain {
			agentID = l.AgentID
		}
		modelName := "unknown"
		if l.Message != nil && l.Message.Model != "" {
			modelName = l.Message.Model
		}

		events = append(events, model.ClaudeCodeEvent{
			Timestamp:                ts,
			SessionID:                l.SessionID,
			ProjectSlug:              projectSlug,
			Cwd:                      l.Cwd,
			GitBranch:                l.GitBranch,
			Model:                    modelName,
			RequestID:                l.RequestID,
			InputTokens:              l.Message.Usage.InputTokens,
			OutputTokens:             l.Message.Usage.OutputTokens,
			CacheReadInputTokens:     l.Message.Usage.CacheReadInputTokens,
			CacheCreationInputTokens: l.Message.Usage.CacheCreationInputTokens,
			AgentID:                  agentID,
		})
	}
	if err := scanner.Err(); err != nil {
		return nil, nil, offset, fmt.Errorf("scan %s: %w", path, err)
	}

	return events, titles, bytesRead, nil
}
