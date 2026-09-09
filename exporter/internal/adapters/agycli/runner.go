// Package agycli implements ports.QuotaRunner by invoking the real `agy`
// binary via subprocess — a Go port of the removed Python
// adapters/agy_cli_runner.py's fetch_usage. Only the zero-cost `/usage`
// meta-command (usage.total_tokens: 0 in agy's own response) is ported —
// see MADR-001 in the removed Python docs/madrs/ for why quota polling,
// not per-task usage, is the primary signal. run_task (a real, costed
// call) has no equivalent here; it belongs to a tracked-call subcommand,
// not the background ingestion loop this exporter runs.
package agycli

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// commandRunner abstracts subprocess invocation — the seam that lets
// FetchQuota's response-parsing logic be tested without spawning a real
// `agy` process. execCommandRunner (below) is the only production
// implementation; tests use a fake.
type commandRunner interface {
	Run(argv []string) (stdout string, err error)
}

type execCommandRunner struct{}

func (execCommandRunner) Run(argv []string) (string, error) {
	cmd := exec.Command(argv[0], argv[1:]...)
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("run %v: %w", argv, err)
	}
	return string(out), nil
}

// Runner is a ports.QuotaRunner backed by the real `agy` binary.
type Runner struct {
	binary string
	runner commandRunner
}

// NewRunner returns a Runner that invokes the real `agy` binary on PATH.
func NewRunner() *Runner {
	return newRunnerWithCommandRunner(execCommandRunner{})
}

func newRunnerWithCommandRunner(r commandRunner) *Runner {
	return &Runner{binary: "agy", runner: r}
}

// usageResponse is the subset of `agy -p "/usage" --output-format json`'s
// shape this runner reads — mirrors AgyCliRunner.fetch_usage's traversal of
// command.data.groups[].buckets[] in the removed Python adapter.
type usageResponse struct {
	Command struct {
		Data struct {
			Groups []struct {
				Name    string `json:"name"`
				Buckets []struct {
					RemainingFraction float64 `json:"remaining_fraction"`
					ResetTime         string  `json:"reset_time"`
				} `json:"buckets"`
			} `json:"groups"`
		} `json:"data"`
	} `json:"command"`
}

func (r *Runner) FetchQuota() ([]model.UsageSnapshot, error) {
	stdout, err := r.runner.Run([]string{r.binary, "-p", "/usage", "--output-format", "json"})
	if err != nil {
		return nil, fmt.Errorf("fetch agy quota: %w", err)
	}

	var resp usageResponse
	if err := json.Unmarshal([]byte(stdout), &resp); err != nil {
		return nil, fmt.Errorf("parse agy usage response: %w", err)
	}

	now := time.Now().UTC()
	var snapshots []model.UsageSnapshot
	for _, group := range resp.Command.Data.Groups {
		for _, bucket := range group.Buckets {
			snapshots = append(snapshots, model.UsageSnapshot{
				Timestamp:         now,
				ModelGroup:        group.Name,
				RemainingFraction: bucket.RemainingFraction,
				ResetTime:         bucket.ResetTime,
			})
		}
	}
	return snapshots, nil
}
