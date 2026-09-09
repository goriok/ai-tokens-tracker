// Package copilot implements ports.CopilotTranscriptReader by reading the
// Copilot CLI's local session-state files directly — a Go port of the
// removed Python adapters/copilot_transcript_reader.py. Zero-cost: these
// are files the Copilot CLI already writes locally (interactive/TUI use
// included), no API call involved.
package copilot

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// Reader reads session-state directories shaped like
// ~/.copilot/session-state: one subdirectory per session_id, events.jsonl
// (+ optional workspace.yaml) inside.
type Reader struct {
	sessionStateDir string
}

func NewReader(sessionStateDir string) *Reader {
	return &Reader{sessionStateDir: sessionStateDir}
}

func (r *Reader) ReadNewEvents(readSessions map[string]bool) ([]model.CopilotEvent, []model.SessionTitle, map[string]bool, error) {
	newReadSessions := make(map[string]bool, len(readSessions))
	for k, v := range readSessions {
		newReadSessions[k] = v
	}

	var events []model.CopilotEvent
	var titles []model.SessionTitle

	info, err := os.Stat(r.sessionStateDir)
	if err != nil || !info.IsDir() {
		return events, titles, newReadSessions, nil // no session-state dir yet is not an error
	}

	sessionDirs, err := os.ReadDir(r.sessionStateDir)
	if err != nil {
		return nil, nil, readSessions, fmt.Errorf("read session-state dir %s: %w", r.sessionStateDir, err)
	}
	sort.Slice(sessionDirs, func(i, j int) bool { return sessionDirs[i].Name() < sessionDirs[j].Name() })

	for _, sessionDir := range sessionDirs {
		if !sessionDir.IsDir() {
			continue
		}
		sessionID := sessionDir.Name()
		dir := filepath.Join(r.sessionStateDir, sessionID)

		// Read the title on every visit, not gated by newReadSessions — the
		// CLI can set/rename workspace.yaml's name after the session was
		// already marked read for token-usage purposes (mirrors the removed
		// Python reader's comment on the same choice).
		if title, ok := parseTitle(filepath.Join(dir, "workspace.yaml")); ok {
			titles = append(titles, model.SessionTitle{SessionID: sessionID, Title: title})
		}

		if newReadSessions[sessionID] {
			continue
		}

		transcriptPath := filepath.Join(dir, "events.jsonl")
		if _, err := os.Stat(transcriptPath); err != nil {
			continue
		}

		event, err := parseSession(sessionID, transcriptPath)
		if err != nil {
			return nil, nil, readSessions, fmt.Errorf("parse session %s: %w", sessionID, err)
		}
		if event == nil {
			continue // still running or crashed before shutdown — retry on a future call
		}
		events = append(events, *event)
		newReadSessions[sessionID] = true
	}

	return events, titles, newReadSessions, nil
}

func parseTitle(path string) (string, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", false
	}
	var workspace struct {
		Name string `yaml:"name"`
	}
	if err := yaml.Unmarshal(data, &workspace); err != nil {
		log.Printf("skipping malformed copilot workspace.yaml %s: %v", path, err)
		return "", false
	}
	name := strings.TrimSpace(workspace.Name)
	if name == "" {
		return "", false
	}
	return name, true
}

type sessionStartLine struct {
	Type string `json:"type"`
	Data struct {
		SessionID string `json:"sessionId"`
		StartTime string `json:"startTime"`
		Context   struct {
			Cwd string `json:"cwd"`
		} `json:"context"`
	} `json:"data"`
}

type sessionShutdownLine struct {
	Type string `json:"type"`
	Data struct {
		CurrentModel string `json:"currentModel"`
		ModelMetrics map[string]struct {
			Usage struct {
				InputTokens      int64 `json:"inputTokens"`
				OutputTokens     int64 `json:"outputTokens"`
				CacheReadTokens  int64 `json:"cacheReadTokens"`
				CacheWriteTokens int64 `json:"cacheWriteTokens"`
			} `json:"usage"`
		} `json:"modelMetrics"`
	} `json:"data"`
}

// typeOnly is decoded first on every line so we know which of the two full
// shapes above to decode into, without re-parsing the JSON bytes twice for
// every line (only the one or two lines of interest get decoded twice).
type typeOnly struct {
	Type string `json:"type"`
}

func parseSession(sessionID, path string) (*model.CopilotEvent, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var cwd, startTime string
	var shutdown *sessionShutdownLine

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		raw := scanner.Bytes()
		var t typeOnly
		if err := json.Unmarshal(raw, &t); err != nil {
			log.Printf("skipping malformed copilot transcript line in %s: %v", path, err)
			continue
		}
		switch t.Type {
		case "session.start":
			var l sessionStartLine
			if err := json.Unmarshal(raw, &l); err != nil {
				log.Printf("skipping malformed copilot session.start line in %s: %v", path, err)
				continue
			}
			cwd = l.Data.Context.Cwd
			startTime = l.Data.StartTime
		case "session.shutdown":
			var l sessionShutdownLine
			if err := json.Unmarshal(raw, &l); err != nil {
				log.Printf("skipping malformed copilot session.shutdown line in %s: %v", path, err)
				continue
			}
			shutdown = &l
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan %s: %w", path, err)
	}

	if shutdown == nil {
		return nil, nil // session still running or crashed before shutdown
	}

	ts, err := model.ParseTimestamp(startTime)
	if err != nil {
		log.Printf("skipping copilot session %s with unparseable startTime %q: %v", sessionID, startTime, err)
		return nil, nil
	}

	var input, output, cacheRead, cacheCreation int64
	for _, metrics := range shutdown.Data.ModelMetrics {
		input += metrics.Usage.InputTokens
		output += metrics.Usage.OutputTokens
		cacheRead += metrics.Usage.CacheReadTokens
		cacheCreation += metrics.Usage.CacheWriteTokens
	}

	modelName := shutdown.Data.CurrentModel
	if modelName == "" {
		modelName = "unknown"
	}

	return &model.CopilotEvent{
		Timestamp:           ts,
		SessionID:           sessionID,
		Cwd:                 cwd,
		Model:               modelName,
		InputTokens:         input,
		OutputTokens:        output,
		CacheReadTokens:     cacheRead,
		CacheCreationTokens: cacheCreation,
	}, nil
}
