// Package tracker implements a real, costed tracked-call — a Go port of
// the removed Python adapters/copilot_cli_runner.py and
// scripts/copilot-track.py. Unlike every other adapter in this exporter,
// this one is NOT zero-cost: it invokes the copilot/agy binary to actually
// run a prompt. It exists to keep .claude/workflows/rag-vs-manual-single-call.js
// (and similar tooling) working without a Python interpreter in the loop.
package tracker

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// commandRunner mirrors adapters/agycli's seam — abstracts subprocess
// invocation so RunCopilotTask's usage-file-parsing logic is testable
// without spawning a real process. Live verification (spawning the real
// `copilot` binary) happens manually, the same discipline used by every
// other adapter here — see docs/madrs/MADR-004.
type commandRunner interface {
	Run(argv []string) (stdout string, err error)
}

type execCommandRunner struct{}

func (execCommandRunner) Run(argv []string) (string, error) {
	cmd := exec.Command(argv[0], argv[1:]...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		// Unlike agycli's quota poll, a failed task call is still a
		// TaskCall (status="ERROR") the caller wants recorded, not a Go
		// error — the removed Python copilot-track.py never treated a
		// non-zero exit as fatal either. Returning stdout+err lets the
		// caller decide.
		return string(out), fmt.Errorf("run %v: %w", argv, err)
	}
	return string(out), nil
}

// CopilotRunner runs a real copilot -p task and returns its token usage as
// a model.TaskCall, ready to be appended to tsdbstore directly (see the
// `track` CLI subcommand) — this bypasses the ingest.Backfill/Incremental
// read-then-batch path entirely, since a tracked call is a single
// known-now event, not something to discover by reading a transcript.
type CopilotRunner struct {
	runner commandRunner
}

func NewCopilotRunner() *CopilotRunner {
	return newCopilotRunnerWithCommandRunner(execCommandRunner{})
}

func newCopilotRunnerWithCommandRunner(r commandRunner) *CopilotRunner {
	return &CopilotRunner{runner: r}
}

// usageFile is the shape of --usage-output-file's JSON — the fields this
// runner reads, mirroring the removed Python CopilotCliRunner.run_task's
// token_details traversal.
type usageFile struct {
	CurrentModel string `json:"currentModel"`
	TokenDetails struct {
		Input      struct{ TokenCount int64 } `json:"input"`
		Output     struct{ TokenCount int64 } `json:"output"`
		CacheRead  struct{ TokenCount int64 } `json:"cache_read"`
		CacheWrite struct{ TokenCount int64 } `json:"cache_write"`
	} `json:"tokenDetails"`
}

// RunCopilotTask runs `copilot -p <prompt> --model <model>
// --allow-all-tools [--disable-builtin-mcps] --usage-output-file <tmp>`,
// mirroring the removed Python CopilotCliRunner's exact flags
// (--disable-builtin-mcps drops ~9.4k tokens of fixed GitHub MCP schema
// overhead per call, confirmed by measurement there) when
// disableBuiltinMCPs is true — the default for every existing caller.
// Passing false omits the flag entirely (the copilot CLI has no negated
// form of it), enabling the with-vs-without-built-in-MCPs comparison. label
// becomes the TaskCall's Task field; if empty, the prompt itself is used
// (truncated to 200 chars, matching the removed Python copilot-track.py).
// Returns the subprocess's stdout too — callers (the `track` CLI
// subcommand) print this as the command's response, matching
// copilot-track.py's behavior of being otherwise transparent to the caller.
func (r *CopilotRunner) RunCopilotTask(prompt, model_, label string, disableBuiltinMCPs bool) (model.TaskCall, string, error) {
	usageFile_, err := os.CreateTemp("", "aitokens-copilot-usage-*.json")
	if err != nil {
		return model.TaskCall{}, "", fmt.Errorf("create temp usage file: %w", err)
	}
	usagePath := usageFile_.Name()
	usageFile_.Close()
	defer os.Remove(usagePath)

	argv := []string{
		"copilot", "-p", prompt,
		"--model", model_,
		"--allow-all-tools",
	}
	if disableBuiltinMCPs {
		argv = append(argv, "--disable-builtin-mcps")
	}
	argv = append(argv, "--usage-output-file", usagePath)

	start := time.Now().UTC()
	stdout, runErr := r.runner.Run(argv)
	duration := time.Since(start).Seconds()

	status := "SUCCESS"
	if runErr != nil {
		status = "ERROR"
	}

	data, readErr := os.ReadFile(usagePath)
	if readErr != nil {
		// No usage file (e.g. the process crashed before writing one) — still
		// record the call, with zeroed tokens, rather than losing the
		// attempt entirely.
		return model.TaskCall{
			Timestamp: start,
			Model:     model_,
			Status:    status,
			DurationS: duration,
			Task:      taskLabel(label, prompt),
			Source:    "copilot",
		}, stdout, nil
	}

	var usage usageFile
	if err := json.Unmarshal(data, &usage); err != nil {
		return model.TaskCall{}, stdout, fmt.Errorf("parse usage file: %w", err)
	}

	resolvedModel := usage.CurrentModel
	if resolvedModel == "" {
		resolvedModel = model_
	}

	call := model.TaskCall{
		Timestamp:           start,
		Model:               resolvedModel,
		Status:              status,
		InputTokens:         usage.TokenDetails.Input.TokenCount,
		OutputTokens:        usage.TokenDetails.Output.TokenCount,
		CacheReadTokens:     usage.TokenDetails.CacheRead.TokenCount,
		CacheCreationTokens: usage.TokenDetails.CacheWrite.TokenCount,
		DurationS:           duration,
		Task:                taskLabel(label, prompt),
		Source:              "copilot",
	}
	call.TotalTokens = call.InputTokens + call.OutputTokens + call.CacheReadTokens + call.CacheCreationTokens

	return call, stdout, nil
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
