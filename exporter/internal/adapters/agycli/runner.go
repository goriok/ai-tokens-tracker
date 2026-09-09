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
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
)

// commandRunner abstracts subprocess invocation — the seam that lets
// FetchQuota's and RunAgyTask's response-parsing logic be tested without
// spawning a real `agy` process. execCommandRunner (below) is the only
// production implementation; tests use a fake. timeout is per-call, not
// fixed at construction: FetchQuota and RunAgyTask need very different
// bounds (see quotaTimeout/taskTimeout) despite sharing this one runner.
type commandRunner interface {
	Run(argv []string, timeout time.Duration) (stdout string, err error)
}

// execCommandRunner enforces a hard timeout on every invocation — found
// necessary by testing against real agy behavior: a -p call to a model
// whose weekly quota is exhausted can hang indefinitely (observed live,
// 15+ minutes with no return). The removed Python AgyCliRunner had
// subprocess.run(..., timeout=600) for run_task and timeout=30 for
// fetch_usage; this port had no timeout at all until that observation.
type execCommandRunner struct{}

func (execCommandRunner) Run(argv []string, timeout time.Duration) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	out, err := cmd.Output()
	if err != nil {
		if ctx.Err() == context.DeadlineExceeded {
			return "", fmt.Errorf("run %v: timed out after %s", argv, timeout)
		}
		return "", fmt.Errorf("run %v: %w", argv, err)
	}
	return string(out), nil
}

// Runner is a ports.QuotaRunner backed by the real `agy` binary.
type Runner struct {
	binary string
	runner commandRunner
}

// quotaTimeout matches the removed Python AgyCliRunner.fetch_usage's
// subprocess.run(..., timeout=30) — /usage is a zero-cost meta-command,
// expected to answer quickly. taskTimeout matches run_task's timeout=600 —
// a real task call can legitimately take minutes.
const (
	quotaTimeout = 30 * time.Second
	taskTimeout  = 600 * time.Second
)

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
	stdout, err := r.runner.Run([]string{r.binary, "-p", "/usage", "--output-format", "json"}, quotaTimeout)
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
