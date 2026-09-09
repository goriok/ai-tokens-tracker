package agycli

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// taskResponse is `agy -p <prompt> --output-format json`'s shape — a Go
// port of AgyCliRunner.run_task's traversal in the removed Python adapter.
type taskResponse struct {
	Status   string `json:"status"`
	Response string `json:"response"`
	Usage    struct {
		InputTokens     int64 `json:"input_tokens"`
		OutputTokens    int64 `json:"output_tokens"`
		ThinkingTokens  int64 `json:"thinking_tokens"`
		TotalTokens     int64 `json:"total_tokens"`
		CacheReadTokens int64 `json:"cache_read_tokens"`
		// agy's CLI output has no cache-write/cache-creation field today —
		// left unread here deliberately, same as the removed Python
		// AgyCliRunner: it defaults to 0, meaning "not reported," not
		// "confirmed zero" (see metrics.TaskCallSamples' handling of
		// Source == "agy" for how that distinction is preserved downstream).
	} `json:"usage"`
}

// RunAgyTask runs `agy -p <prompt> --model <model> --output-format json`
// (plus `--effort <effort>` when given), mirroring the removed Python
// AgyCliRunner.run_task. label becomes the TaskCall's Task field; if
// empty, the prompt itself is used (truncated to 200 chars, matching the
// removed Python agy-track.py/agy-delegate.py). Returns the task's
// response text too — callers (the `track`/`delegate` CLI subcommands)
// print this, matching the removed scripts' behavior of being otherwise
// transparent to the caller.
func (r *Runner) RunAgyTask(prompt, model_, effort, label string) (model.TaskCall, string, error) {
	argv := []string{r.binary, "-p", prompt, "--model", model_, "--output-format", "json"}
	if effort != "" {
		argv = append(argv, "--effort", effort)
	}

	start := time.Now().UTC()
	stdout, runErr := r.runner.Run(argv, taskTimeout)
	duration := time.Since(start).Seconds()

	if runErr != nil {
		return model.TaskCall{
			Timestamp: start,
			Model:     model_,
			Status:    "ERROR",
			DurationS: duration,
			Task:      taskLabel(label, prompt),
			Source:    "agy",
		}, "", nil
	}

	var resp taskResponse
	if err := json.Unmarshal([]byte(stdout), &resp); err != nil {
		return model.TaskCall{}, "", fmt.Errorf("parse agy task response: %w", err)
	}

	status := resp.Status
	if status == "" {
		status = "UNKNOWN"
	}

	call := model.TaskCall{
		Timestamp:       start,
		Model:           model_,
		Status:          status,
		InputTokens:     resp.Usage.InputTokens,
		OutputTokens:    resp.Usage.OutputTokens,
		ThinkingTokens:  resp.Usage.ThinkingTokens,
		TotalTokens:     resp.Usage.TotalTokens,
		CacheReadTokens: resp.Usage.CacheReadTokens,
		DurationS:       duration,
		Task:            taskLabel(label, prompt),
		Source:          "agy",
	}
	return call, resp.Response, nil
}

func taskLabel(label, prompt string) string {
	s := label
	if s == "" {
		s = prompt
	}
	if len(s) > 200 {
		s = s[:200]
	}
	return s
}
