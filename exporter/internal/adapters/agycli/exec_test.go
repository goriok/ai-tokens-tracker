package agycli

import (
	"testing"
	"time"
)

// TestExecCommandRunner_KillsProcessPastTimeout is the seam for a real bug
// found by testing against real agy behavior: a `-p` call to a model whose
// weekly quota is exhausted can hang indefinitely (observed live — a task
// call to a quota-exhausted model never returned even after 15+ minutes).
// The removed Python AgyCliRunner.run_task had subprocess.run(...,
// timeout=600); the Go port had none at all until this test caught it.
// Uses `sleep` as a stand-in for a hung `agy` process — this is a property
// of execCommandRunner itself (real subprocess invocation), not something
// the fakeCommandRunner used elsewhere in this package could exercise.
func TestExecCommandRunner_KillsProcessPastTimeout(t *testing.T) {
	runner := execCommandRunner{}

	start := time.Now()
	_, err := runner.Run([]string{"sleep", "10"}, 100*time.Millisecond)
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected an error when the process is killed for exceeding the timeout")
	}
	if elapsed > 2*time.Second {
		t.Errorf("Run took %v, want it to return shortly after the 100ms timeout, not wait for sleep's own 10s", elapsed)
	}
}

func TestExecCommandRunner_ReturnsOutputWhenWithinTimeout(t *testing.T) {
	runner := execCommandRunner{}

	out, err := runner.Run([]string{"echo", "hello"}, 5*time.Second)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if out != "hello\n" {
		t.Errorf("out = %q, want %q", out, "hello\n")
	}
}
