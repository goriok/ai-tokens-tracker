// Command aitokens-exporter reads token usage from the Python side's
// SQLite store and, eventually, serves it as a Prometheus-queryable
// timeseries. See docs/madrs/MADR-003 for the architecture.
package main

import (
	"context"
	"encoding/json"
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

	"github.com/goriok/ai-tokens-tracker/exporter/internal/checkpoint"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/httpapi"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/ingest"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/metrics"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/sqlitesource"
	"github.com/goriok/ai-tokens-tracker/exporter/internal/tsdbstore"
)

func defaultDBPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".local", "share", "ai-tokens-tracker", "usage.db")
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
		fmt.Fprintln(os.Stderr, "usage: aitokens-exporter <dump|backfill|serve> [flags]")
		os.Exit(2)
	}

	switch os.Args[1] {
	case "dump":
		runDump(os.Args[2:])
	case "backfill":
		runBackfill(os.Args[2:])
	case "serve":
		runServe(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(2)
	}
}

// runServe is Phase 4's long-running process: incremental ingestion on a
// timer, plus an HTTP server exposing /metrics (current state) and
// /-/healthy. Requires a completed backfill (ingest.Backfill via the
// backfill subcommand) — refuses to start incremental ingestion into a
// store with no BackfillCompletedAt, since Incremental's checkpoint-based
// delta reads assume the historical data is already in place.
func runServe(args []string) {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	dbPath := fs.String("db", defaultDBPath(), "path to usage.db (read-only)")
	tsdbDir := fs.String("tsdb", defaultTSDBDir(), "directory for the append-only samples log")
	listen := fs.String("listen", "127.0.0.1:9464", "address to serve /metrics on")
	interval := fs.Duration("interval", time.Minute, "how often to run an incremental ingest cycle")
	fs.Parse(args)

	src, err := sqlitesource.Open(*dbPath)
	must(err)
	defer src.Close()

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

	runIngestLoop(ctx, src, store, acc, cp, *tsdbDir, *interval)

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
func runIngestLoop(ctx context.Context, src *sqlitesource.Source, store *tsdbstore.Store, acc *metrics.Accumulator, cp checkpoint.State, tsdbDir string, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	runCycle := func() {
		result, err := ingest.Incremental(src, store, acc, cp)
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
			log.Printf("ingest cycle: %d raw samples, %d bad rows, %d written",
				result.RawSamples, result.BadRows, result.Written)
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

// runBackfill is Phase 3's verification tool: one-shot, ordered append of
// the entire history from usage.db into the local tsdbstore. See
// ingest.Backfill and MADR-003 for why this must sort globally by
// timestamp rather than relying on any out-of-order window.
func runBackfill(args []string) {
	fs := flag.NewFlagSet("backfill", flag.ExitOnError)
	dbPath := fs.String("db", defaultDBPath(), "path to usage.db (read-only)")
	tsdbDir := fs.String("tsdb", defaultTSDBDir(), "directory for the append-only samples log")
	force := fs.Bool("force", false, "re-run even if a backfill already completed")
	fs.Parse(args)

	src, err := sqlitesource.Open(*dbPath)
	must(err)
	defer src.Close()

	store, err := tsdbstore.Open(*tsdbDir)
	must(err)
	defer store.Close()

	cp, err := checkpoint.Load(*tsdbDir)
	must(err)

	result, err := ingest.Backfill(src, store, cp, *force, time.Now().UTC().Format(time.RFC3339))
	must(err)

	must(checkpoint.Save(*tsdbDir, result.NewCheckpoint))

	fmt.Printf("backfill complete: %d raw samples, %d bad rows, %d written to %s\n",
		result.RawSamples, result.BadRows, result.Written, *tsdbDir)
	fmt.Printf("checkpoint: %+v\n", result.NewCheckpoint)
}

// runDump is Phase 1's verification tool: proves the Go side reads the same
// rows the Python side writes, without touching the TSDB yet.
func runDump(args []string) {
	fs := flag.NewFlagSet("dump", flag.ExitOnError)
	dbPath := fs.String("db", defaultDBPath(), "path to usage.db (read-only)")
	limit := fs.Int("limit", 10, "max rows to print per table")
	fs.Parse(args)

	src, err := sqlitesource.Open(*dbPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "open %s: %v\n", *dbPath, err)
		os.Exit(1)
	}
	defer src.Close()

	ccEvents, ccMax, ccBad, err := src.ClaudeCodeEventsSince(0)
	must(err)
	copilotEvents, coMax, coBad, err := src.CopilotEventsSince(0)
	must(err)
	taskCalls, tcMax, tcBad, err := src.TaskCallsSince(0)
	must(err)
	snapshots, usMax, usBad, err := src.UsageSnapshotsSince(0)
	must(err)

	printTable("claude_code_usage_events", truncate(ccEvents, *limit), len(ccEvents), ccMax, ccBad)
	printTable("copilot_usage_events", truncate(copilotEvents, *limit), len(copilotEvents), coMax, coBad)
	printTable("task_calls", truncate(taskCalls, *limit), len(taskCalls), tcMax, tcBad)
	printTable("usage_snapshots", truncate(snapshots, *limit), len(snapshots), usMax, usBad)
}

func truncate[T any](s []T, n int) []T {
	if len(s) > n {
		return s[:n]
	}
	return s
}

func printTable(name string, sample any, total int, maxID int64, badRows int) {
	fmt.Printf("=== %s (total=%d, max_id=%d, bad_rows=%d) ===\n", name, total, maxID, badRows)
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(sample)
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
