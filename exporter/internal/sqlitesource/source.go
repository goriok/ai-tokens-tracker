// Package sqlitesource reads new rows from the Python side's usage.db,
// read-only, by primary-key id — never by timestamp. Timestamps aren't
// monotonic with id (a transcript discovered late can carry an older
// timestamp than rows already ingested), so an id-ordered cursor is the only
// cursor that can't skip a row. See MADR-003 for the measurement backing this.
package sqlitesource

import (
	"database/sql"
	"fmt"

	_ "modernc.org/sqlite"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// Source is a read-only handle onto the Python usage.db.
type Source struct {
	db *sql.DB
}

// Open connects read-only, with a busy timeout so a concurrent Python writer
// (WAL mode) never fails this reader outright — it waits instead.
func Open(path string) (*Source, error) {
	dsn := fmt.Sprintf("file:%s?mode=ro&_pragma=busy_timeout(5000)", path)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w", path, err)
	}
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping %s: %w", path, err)
	}
	return &Source{db: db}, nil
}

func (s *Source) Close() error {
	return s.db.Close()
}

// ClaudeCodeEventsSince returns every claude_code_usage_events row with
// id > afterID, ordered by id (arrival order — see package doc). Rows whose
// timestamp fails to parse are skipped, not fatal, and reported via badRows.
func (s *Source) ClaudeCodeEventsSince(afterID int64) (events []model.ClaudeCodeEvent, maxID int64, badRows int, err error) {
	rows, err := s.db.Query(
		`SELECT id, timestamp, session_id, project_slug, cwd, git_branch, model,
		        request_id, input_tokens, output_tokens,
		        cache_read_input_tokens, cache_creation_input_tokens, agent_id
		 FROM claude_code_usage_events WHERE id > ? ORDER BY id`,
		afterID,
	)
	if err != nil {
		return nil, afterID, 0, fmt.Errorf("query claude_code_usage_events: %w", err)
	}
	defer rows.Close()

	maxID = afterID
	for rows.Next() {
		var (
			id                                                  int64
			ts, sessionID, projectSlug, model_, requestID       string
			cwd, gitBranch, agentID                             sql.NullString
			inputTokens, outputTokens, cacheRead, cacheCreation int64
		)
		if err := rows.Scan(&id, &ts, &sessionID, &projectSlug, &cwd, &gitBranch,
			&model_, &requestID, &inputTokens, &outputTokens, &cacheRead, &cacheCreation, &agentID); err != nil {
			return nil, maxID, badRows, fmt.Errorf("scan claude_code_usage_events row: %w", err)
		}
		if id > maxID {
			maxID = id
		}
		parsedTS, perr := parseTimestamp(ts)
		if perr != nil {
			badRows++
			continue
		}
		events = append(events, model.ClaudeCodeEvent{
			ID:                       id,
			Timestamp:                parsedTS,
			SessionID:                sessionID,
			ProjectSlug:              projectSlug,
			Cwd:                      cwd.String,
			GitBranch:                gitBranch.String,
			Model:                    model_,
			RequestID:                requestID,
			InputTokens:              inputTokens,
			OutputTokens:             outputTokens,
			CacheReadInputTokens:     cacheRead,
			CacheCreationInputTokens: cacheCreation,
			AgentID:                  agentID.String,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, maxID, badRows, fmt.Errorf("iterate claude_code_usage_events: %w", err)
	}
	return events, maxID, badRows, nil
}

// CopilotEventsSince mirrors ClaudeCodeEventsSince for copilot_usage_events.
// A row whose timestamp is empty — no session.start recorded, see
// adapters/copilot_transcript_reader.py:121 — is a bad row like any other
// unparseable timestamp: skipped, never appended with a zero time.
func (s *Source) CopilotEventsSince(afterID int64) (events []model.CopilotEvent, maxID int64, badRows int, err error) {
	rows, err := s.db.Query(
		`SELECT id, timestamp, session_id, cwd, model,
		        input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
		 FROM copilot_usage_events WHERE id > ? ORDER BY id`,
		afterID,
	)
	if err != nil {
		return nil, afterID, 0, fmt.Errorf("query copilot_usage_events: %w", err)
	}
	defer rows.Close()

	maxID = afterID
	for rows.Next() {
		var (
			id                                                  int64
			ts, sessionID, model_                               string
			cwd                                                 sql.NullString
			inputTokens, outputTokens, cacheRead, cacheCreation int64
		)
		if err := rows.Scan(&id, &ts, &sessionID, &cwd, &model_,
			&inputTokens, &outputTokens, &cacheRead, &cacheCreation); err != nil {
			return nil, maxID, badRows, fmt.Errorf("scan copilot_usage_events row: %w", err)
		}
		if id > maxID {
			maxID = id
		}
		parsedTS, perr := parseTimestamp(ts)
		if perr != nil {
			badRows++
			continue
		}
		events = append(events, model.CopilotEvent{
			ID:                  id,
			Timestamp:           parsedTS,
			SessionID:           sessionID,
			Cwd:                 cwd.String,
			Model:               model_,
			InputTokens:         inputTokens,
			OutputTokens:        outputTokens,
			CacheReadTokens:     cacheRead,
			CacheCreationTokens: cacheCreation,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, maxID, badRows, fmt.Errorf("iterate copilot_usage_events: %w", err)
	}
	return events, maxID, badRows, nil
}

// TaskCallsSince mirrors ClaudeCodeEventsSince for task_calls.
func (s *Source) TaskCallsSince(afterID int64) (calls []model.TaskCall, maxID int64, badRows int, err error) {
	rows, err := s.db.Query(
		`SELECT id, timestamp, model, status, input_tokens, output_tokens, thinking_tokens,
		        total_tokens, duration_s, task, cache_read_tokens, source, cache_creation_tokens,
		        confidence_score
		 FROM task_calls WHERE id > ? ORDER BY id`,
		afterID,
	)
	if err != nil {
		return nil, afterID, 0, fmt.Errorf("query task_calls: %w", err)
	}
	defer rows.Close()

	maxID = afterID
	for rows.Next() {
		var (
			id                                                                               int64
			ts, model_, status, task, source                                                 string
			inputTokens, outputTokens, thinkingTokens, totalTokens, cacheRead, cacheCreation int64
			durationS                                                                        float64
			confidenceScore                                                                  sql.NullFloat64
		)
		if err := rows.Scan(&id, &ts, &model_, &status, &inputTokens, &outputTokens, &thinkingTokens,
			&totalTokens, &durationS, &task, &cacheRead, &source, &cacheCreation, &confidenceScore); err != nil {
			return nil, maxID, badRows, fmt.Errorf("scan task_calls row: %w", err)
		}
		if id > maxID {
			maxID = id
		}
		parsedTS, perr := parseTimestamp(ts)
		if perr != nil {
			badRows++
			continue
		}
		call := model.TaskCall{
			ID:                  id,
			Timestamp:           parsedTS,
			Model:               model_,
			Status:              status,
			InputTokens:         inputTokens,
			OutputTokens:        outputTokens,
			ThinkingTokens:      thinkingTokens,
			TotalTokens:         totalTokens,
			DurationS:           durationS,
			Task:                task,
			CacheReadTokens:     cacheRead,
			Source:              source,
			CacheCreationTokens: cacheCreation,
		}
		if confidenceScore.Valid {
			v := confidenceScore.Float64
			call.ConfidenceScore = &v
		}
		calls = append(calls, call)
	}
	if err := rows.Err(); err != nil {
		return nil, maxID, badRows, fmt.Errorf("iterate task_calls: %w", err)
	}
	return calls, maxID, badRows, nil
}

// UsageSnapshotsSince mirrors ClaudeCodeEventsSince for usage_snapshots.
func (s *Source) UsageSnapshotsSince(afterID int64) (snapshots []model.UsageSnapshot, maxID int64, badRows int, err error) {
	rows, err := s.db.Query(
		`SELECT id, timestamp, model_group, remaining_fraction, reset_time
		 FROM usage_snapshots WHERE id > ? ORDER BY id`,
		afterID,
	)
	if err != nil {
		return nil, afterID, 0, fmt.Errorf("query usage_snapshots: %w", err)
	}
	defer rows.Close()

	maxID = afterID
	for rows.Next() {
		var (
			id                int64
			ts, modelGroup    string
			remainingFraction float64
			resetTime         sql.NullString
		)
		if err := rows.Scan(&id, &ts, &modelGroup, &remainingFraction, &resetTime); err != nil {
			return nil, maxID, badRows, fmt.Errorf("scan usage_snapshots row: %w", err)
		}
		if id > maxID {
			maxID = id
		}
		parsedTS, perr := parseTimestamp(ts)
		if perr != nil {
			badRows++
			continue
		}
		snapshots = append(snapshots, model.UsageSnapshot{
			ID:                id,
			Timestamp:         parsedTS,
			ModelGroup:        modelGroup,
			RemainingFraction: remainingFraction,
			ResetTime:         resetTime.String,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, maxID, badRows, fmt.Errorf("iterate usage_snapshots: %w", err)
	}
	return snapshots, maxID, badRows, nil
}
