// Command aitokens-exporter reads token usage from the Python side's
// SQLite store and, eventually, serves it as a Prometheus-queryable
// timeseries. See docs/madrs/MADR-003 for the architecture.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/goriok/ai-tokens-tracker/exporter/internal/sqlitesource"
)

func defaultDBPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".local", "share", "ai-tokens-tracker", "usage.db")
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: aitokens-exporter <dump> [flags]")
		os.Exit(2)
	}

	switch os.Args[1] {
	case "dump":
		runDump(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(2)
	}
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
