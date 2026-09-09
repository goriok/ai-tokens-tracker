// Command aitokens-exporter reads AI CLI token usage directly from local
// transcripts and CLI subprocess calls, and serves it as a
// Prometheus-queryable timeseries. See docs/madrs/MADR-003 and MADR-004
// for the architecture.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/adapters/agycli"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/adapters/claudecode"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/adapters/copilot"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/adapters/tracker"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/checkpoint"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/httpapi"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/ingest"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/model"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/modelpolicy"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/ports"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/tsdbstore"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/vmimport"
)

func defaultProjectsDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".claude", "projects")
}

func defaultSessionStateDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".copilot", "session-state")
}

func defaultTSDBDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".local", "share", "ai-tokens-tracker", "tsdb")
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: aitokens-exporter <backfill|serve|export-vm|track> [flags]")
		os.Exit(2)
	}

	switch os.Args[1] {
	case "backfill":
		runBackfill(os.Args[2:])
	case "serve":
		runServe(os.Args[2:])
	case "export-vm":
		runExportVM(os.Args[2:])
	case "track":
		runTrack(os.Args[2:])
	case "delegate":
		runDelegate(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(2)
	}
}

// recordTaskCall appends one tracked call's token usage directly to
// tsdbstore, seeded from the store's own current state so the running
// counters aren't reset — shared by runTrack and runDelegate, since both
// are "a single known-now event," not a batch discovered by reading a
// transcript (see ingest.Incremental for that path instead).
func recordTaskCall(tsdbDir string, call model.TaskCall) error {
	store, err := tsdbstore.Open(tsdbDir)
	if err != nil {
		return err
	}
	defer store.Close()

	acc := metrics.NewAccumulator()
	store.SeedAccumulator(acc)
	samples := acc.ApplyAll(metrics.TaskCallSamples(call))
	_, err = store.AppendBatch(samples)
	return err
}

// runTrack runs a real, costed -p task via copilot or agy and appends its
// token usage directly to tsdbstore, then prints the task's own response
// to stdout — a drop-in replacement for the removed Python
// scripts/copilot-track.py and scripts/agy-track.py, used by
// .claude/workflows/rag-vs-manual-single-call.js and similar tooling.
func runTrack(args []string) {
	fs := flag.NewFlagSet("track", flag.ExitOnError)
	tool := fs.String("tool", "copilot", "which CLI to track: copilot or agy")
	modelFlag := fs.String("model", "auto", "model to request")
	effort := fs.String("effort", "", "agy only: effort level to request")
	task := fs.String("task", "", "short label for this call; defaults to the prompt")
	tsdbDir := fs.String("tsdb", defaultTSDBDir(), "directory for the append-only samples log")
	fs.Parse(args)

	promptArgs := fs.Args()
	if len(promptArgs) != 1 {
		fmt.Fprintln(os.Stderr, "usage: aitokens-exporter track [--tool copilot|agy] [--model auto] [--task label] '<prompt>'")
		os.Exit(2)
	}
	prompt := promptArgs[0]

	var (
		call   model.TaskCall
		stdout string
		err    error
	)
	switch *tool {
	case "copilot":
		call, stdout, err = tracker.NewCopilotRunner().RunCopilotTask(prompt, *modelFlag, *task)
	case "agy":
		call, stdout, err = agycli.NewRunner().RunAgyTask(prompt, *modelFlag, *effort, *task)
	default:
		fmt.Fprintf(os.Stderr, "unsupported --tool %q (expected copilot or agy)\n", *tool)
		os.Exit(2)
	}
	must(err)
	must(recordTaskCall(*tsdbDir, call))
	fmt.Print(stdout)
}

// runDelegate picks a model for the given task complexity via
// modelpolicy.ChooseModel (steering away from a model group whose weekly
// quota is running low, per the current agy quota poll), then runs the
// task via agy -p and records it — a drop-in replacement for the removed
// Python scripts/agy-delegate.py.
func runDelegate(args []string) {
	fs := flag.NewFlagSet("delegate", flag.ExitOnError)
	complexity := fs.String("complexity", "medium", "task complexity: low, medium, or high")
	modelFlag := fs.String("model", "", "skip auto-pick and use this model directly")
	effort := fs.String("effort", "", "effort level to request")
	task := fs.String("task", "", "short label for this call; defaults to the prompt")
	tsdbDir := fs.String("tsdb", defaultTSDBDir(), "directory for the append-only samples log")
	fs.Parse(args)

	promptArgs := fs.Args()
	if len(promptArgs) != 1 {
		fmt.Fprintln(os.Stderr, "usage: aitokens-exporter delegate [--complexity low|medium|high] [--model <model>] [--task label] '<prompt>'")
		os.Exit(2)
	}
	prompt := promptArgs[0]

	quota := agycli.NewRunner()

	chosenModel := *modelFlag
	if chosenModel == "" {
		snapshots, err := quota.FetchQuota()
		must(err)
		chosenModel, err = modelpolicy.ChooseModel(*complexity, snapshots)
		must(err)
		fmt.Fprintf(os.Stderr, "[delegate] complexity=%s -> model=%s\n", *complexity, chosenModel)
	}

	call, stdout, err := quota.RunAgyTask(prompt, chosenModel, *effort, *task)
	must(err)
	must(recordTaskCall(*tsdbDir, call))
	fmt.Print(stdout)
}

// runExportVM pushes the full historical log — every sample ever appended
// by backfill/incremental ingestion, with its real timestamp — into a
// running VictoriaMetrics via /api/v1/import. This is what makes vmui/PromQL
// show real history instead of only what's been scraped since VM started:
// a scrape of /metrics can only ever see "now" (see MADR-003 and
// vmimport's package doc). Safe to re-run: VictoriaMetrics accepts
// re-importing the same (series, timestamp, value) as a no-op.
func runExportVM(args []string) {
	fs := flag.NewFlagSet("export-vm", flag.ExitOnError)
	tsdbDir := fs.String("tsdb", defaultTSDBDir(), "directory holding the append-only samples log")
	vmURL := fs.String("vm-url", "http://127.0.0.1:8428", "VictoriaMetrics base URL")
	fs.Parse(args)

	store, err := tsdbstore.Open(*tsdbDir)
	must(err)
	defer store.Close()

	samples, err := store.AllSamples()
	must(err)

	must(vmimport.Import(*vmURL, samples))
	fmt.Printf("exported %d samples to %s/api/v1/import\n", len(samples), *vmURL)
}

// runServe is the long-running process: incremental ingestion on a timer,
// plus an HTTP server exposing /metrics (current state) and /-/healthy.
// Requires a completed backfill (ingest.Backfill via the backfill
// subcommand) — refuses to start incremental ingestion into a store with
// no BackfillCompletedAt, since Incremental's checkpoint-based delta reads
// assume the historical data is already in place.
func runServe(args []string) {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	tsdbDir := fs.String("tsdb", defaultTSDBDir(), "directory for the append-only samples log")
	listen := fs.String("listen", "127.0.0.1:9464", "address to serve /metrics on")
	interval := fs.Duration("interval", time.Minute, "how often to run an incremental ingest cycle")
	projectsDir := fs.String("projects-dir", defaultProjectsDir(), "Claude Code transcripts directory")
	sessionStateDir := fs.String("session-state-dir", defaultSessionStateDir(), "Copilot session-state directory")
	fs.Parse(args)

	ccReader := claudecode.NewReader(*projectsDir)
	copilotReader := copilot.NewReader(*sessionStateDir)
	quota := agycli.NewRunner()

	store, err := tsdbstore.Open(*tsdbDir)
	must(err)
	defer store.Close()

	cp, err := checkpoint.Load(*tsdbDir)
	must(err)
	if cp.BackfillCompletedAt == "" {
		fmt.Fprintln(os.Stderr, "no completed backfill found — run `aitokens-exporter backfill` first")
		os.Exit(1)
	}

	acc := metrics.NewAccumulator()
	store.SeedAccumulator(acc)

	mux := http.NewServeMux()
	mux.Handle("/metrics", httpapi.MetricsHandler(store))
	mux.Handle("/-/healthy", httpapi.HealthHandler())
	server := &http.Server{Addr: *listen, Handler: mux}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		log.Printf("serving /metrics on http://%s", *listen)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("http server: %v", err)
		}
	}()

	runIngestLoop(ctx, ccReader, copilotReader, quota, store, acc, cp, *tsdbDir, *interval)

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		log.Printf("http server shutdown: %v", err)
	}
}

// runIngestLoop runs ingest.Incremental on a ticker until ctx is canceled
// (SIGINT/SIGTERM). Each cycle's new checkpoint becomes next cycle's input,
// and is persisted to disk right after a successful append — see
// ingest.Incremental and checkpoint.Save's atomicity for why that order
// matters (a crash between append and checkpoint save just means a
// harmless reprocessed batch next cycle, never lost data).
func runIngestLoop(
	ctx context.Context,
	ccReader ports.ClaudeCodeTranscriptReader,
	copilotReader ports.CopilotTranscriptReader,
	quota ports.QuotaRunner,
	store *tsdbstore.Store,
	acc *metrics.Accumulator,
	cp checkpoint.State,
	tsdbDir string,
	interval time.Duration,
) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	runCycle := func() {
		result, err := ingest.Incremental(ccReader, copilotReader, quota, store, acc, cp)
		if err != nil {
			log.Printf("ingest cycle failed: %v", err)
			return
		}
		cp = result.NewCheckpoint
		if err := checkpoint.Save(tsdbDir, cp); err != nil {
			log.Printf("save checkpoint: %v", err)
			return
		}
		if result.RawSamples > 0 {
			log.Printf("ingest cycle: %d raw samples, %d written", result.RawSamples, result.Written)
		}
	}

	runCycle() // first cycle immediately, not after the first interval wait
	for {
		select {
		case <-ctx.Done():
			log.Println("shutting down ingest loop")
			return
		case <-ticker.C:
			runCycle()
		}
	}
}

// runBackfill is a one-shot, ordered append of the entire available
// history from local transcripts and the current agy quota into the local
// tsdbstore. See ingest.Backfill and MADR-003 for why this must sort
// globally by timestamp rather than relying on any out-of-order window.
func runBackfill(args []string) {
	fs := flag.NewFlagSet("backfill", flag.ExitOnError)
	tsdbDir := fs.String("tsdb", defaultTSDBDir(), "directory for the append-only samples log")
	force := fs.Bool("force", false, "re-run even if a backfill already completed")
	projectsDir := fs.String("projects-dir", defaultProjectsDir(), "Claude Code transcripts directory")
	sessionStateDir := fs.String("session-state-dir", defaultSessionStateDir(), "Copilot session-state directory")
	fs.Parse(args)

	ccReader := claudecode.NewReader(*projectsDir)
	copilotReader := copilot.NewReader(*sessionStateDir)
	quota := agycli.NewRunner()

	store, err := tsdbstore.Open(*tsdbDir)
	must(err)
	defer store.Close()

	cp, err := checkpoint.Load(*tsdbDir)
	must(err)

	result, err := ingest.Backfill(ccReader, copilotReader, quota, store, cp, *force, time.Now().UTC().Format(time.RFC3339))
	must(err)

	must(checkpoint.Save(*tsdbDir, result.NewCheckpoint))

	fmt.Printf("backfill complete: %d raw samples, %d written to %s\n", result.RawSamples, result.Written, *tsdbDir)
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
