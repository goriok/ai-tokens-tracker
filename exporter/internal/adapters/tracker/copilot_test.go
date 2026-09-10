package tracker

import (
	"os"
	"path/filepath"
	"testing"
)

// fakeCommandRunner is the seam: stands in for the real `copilot`/`agy`
// subprocess invocation, so RunCopilotTask's parsing of --usage-output-file
// is tested without spawning a real process. writeUsageFile lets the fake
// simulate what the real binary does — write the usage JSON to the path it
// was given as an argument — since RunCopilotTask reads that file after
// the subprocess exits, not its stdout.
type fakeCommandRunner struct {
	stdout        string
	err           error
	usageFileJSON string // written to the --usage-output-file path the caller passed, if non-empty
	gotArgv       []string
}

func (f *fakeCommandRunner) Run(argv []string) (string, error) {
	f.gotArgv = argv
	if f.usageFileJSON != "" {
		for i, a := range argv {
			if a == "--usage-output-file" && i+1 < len(argv) {
				if err := os.WriteFile(argv[i+1], []byte(f.usageFileJSON), 0o600); err != nil {
					return "", err
				}
			}
		}
	}
	return f.stdout, f.err
}

// realCopilotUsageFileJSON is the actual content of a --usage-output-file
// from a real (cheap, deliberately trivial-prompt) `copilot -p` call on
// this machine — see the package's live-verification note for why this is
// safe to have captured once for real.
const realCopilotUsageFileJSON = `{
  "totalPremiumRequestCost": 1,
  "tokenDetails": {
    "input": {"tokenCount": 3},
    "cache_read": {"tokenCount": 0},
    "cache_write": {"tokenCount": 16896},
    "output": {"tokenCount": 5}
  },
  "currentModel": "gpt-5.6-luna"
}`

func TestRunCopilotTask_ParsesRealUsageFileShape(t *testing.T) {
	fake := &fakeCommandRunner{stdout: "ok\n", usageFileJSON: realCopilotUsageFileJSON}
	runner := newCopilotRunnerWithCommandRunner(fake)

	call, _, err := runner.RunCopilotTask("responda apenas: ok", "auto", "smoke-test", true)
	if err != nil {
		t.Fatalf("RunCopilotTask: %v", err)
	}

	if call.Model != "gpt-5.6-luna" {
		t.Errorf("Model = %q, want gpt-5.6-luna (resolved from currentModel, not the requested 'auto')", call.Model)
	}
	if call.InputTokens != 3 || call.OutputTokens != 5 || call.CacheReadTokens != 0 || call.CacheCreationTokens != 16896 {
		t.Errorf("tokens = %d/%d/%d/%d, want 3/5/0/16896",
			call.InputTokens, call.OutputTokens, call.CacheReadTokens, call.CacheCreationTokens)
	}
	if call.Source != "copilot" {
		t.Errorf("Source = %q, want copilot", call.Source)
	}
	if call.Status != "SUCCESS" {
		t.Errorf("Status = %q, want SUCCESS", call.Status)
	}
	if call.Task != "smoke-test" {
		t.Errorf("Task = %q, want smoke-test (the label, not the prompt)", call.Task)
	}
}

func TestRunCopilotTask_TaskDefaultsToPromptWhenLabelEmpty(t *testing.T) {
	fake := &fakeCommandRunner{stdout: "ok\n", usageFileJSON: realCopilotUsageFileJSON}
	runner := newCopilotRunnerWithCommandRunner(fake)

	call, _, err := runner.RunCopilotTask("responda apenas: ok", "auto", "", true)
	if err != nil {
		t.Fatalf("RunCopilotTask: %v", err)
	}
	if call.Task != "responda apenas: ok" {
		t.Errorf("Task = %q, want the prompt itself when no label given", call.Task)
	}
}

func TestRunCopilotTask_InvokesExpectedFlags(t *testing.T) {
	fake := &fakeCommandRunner{stdout: "ok\n", usageFileJSON: realCopilotUsageFileJSON}
	runner := newCopilotRunnerWithCommandRunner(fake)

	if _, _, err := runner.RunCopilotTask("hello", "auto", "", true); err != nil {
		t.Fatalf("RunCopilotTask: %v", err)
	}

	argv := fake.gotArgv
	wantFlags := []string{"--allow-all-tools", "--disable-builtin-mcps", "--usage-output-file"}
	for _, flag := range wantFlags {
		var found bool
		for _, a := range argv {
			if a == flag {
				found = true
			}
		}
		if !found {
			t.Errorf("argv %v missing expected flag %q", argv, flag)
		}
	}
	if argv[0] != "copilot" {
		t.Errorf("argv[0] = %q, want copilot", argv[0])
	}
}

// TestRunCopilotTask_BuiltinMCPsCanBeKeptEnabled is the seam for the
// with-vs-without-built-in-MCPs experiment: disableBuiltinMCPs=false must
// omit --disable-builtin-mcps entirely, not pass some "false" form of it —
// the copilot CLI flag is a presence-only switch, it has no negated form.
func TestRunCopilotTask_BuiltinMCPsCanBeKeptEnabled(t *testing.T) {
	fake := &fakeCommandRunner{stdout: "ok\n", usageFileJSON: realCopilotUsageFileJSON}
	runner := newCopilotRunnerWithCommandRunner(fake)

	if _, _, err := runner.RunCopilotTask("hello", "auto", "", false); err != nil {
		t.Fatalf("RunCopilotTask: %v", err)
	}

	for _, a := range fake.gotArgv {
		if a == "--disable-builtin-mcps" {
			t.Errorf("argv %v should not contain --disable-builtin-mcps when disableBuiltinMCPs=false", fake.gotArgv)
		}
	}
}

func TestRunCopilotTask_UsageFileCleanedUpAfterCall(t *testing.T) {
	fake := &fakeCommandRunner{stdout: "ok\n", usageFileJSON: realCopilotUsageFileJSON}
	runner := newCopilotRunnerWithCommandRunner(fake)

	if _, _, err := runner.RunCopilotTask("hello", "auto", "", true); err != nil {
		t.Fatalf("RunCopilotTask: %v", err)
	}

	var usagePath string
	for i, a := range fake.gotArgv {
		if a == "--usage-output-file" {
			usagePath = fake.gotArgv[i+1]
		}
	}
	if usagePath == "" {
		t.Fatal("no --usage-output-file path recorded")
	}
	if _, err := os.Stat(usagePath); !os.IsNotExist(err) {
		t.Errorf("expected temp usage file %s to be removed after the call, stat err = %v", usagePath, err)
	}
	if filepath.Dir(usagePath) == "" {
		t.Error("usage file path had no directory component")
	}
}
