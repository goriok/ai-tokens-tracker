package agycli

import "testing"

const fakeAgyTaskResponse = `{
  "conversation_id": "",
  "status": "SUCCESS",
  "response": "ok",
  "usage": {
    "input_tokens": 120,
    "output_tokens": 40,
    "thinking_tokens": 10,
    "total_tokens": 170,
    "cache_read_tokens": 5
  }
}`

func TestRunAgyTask_ParsesResponseShape(t *testing.T) {
	fake := &fakeCommandRunner{stdout: fakeAgyTaskResponse}
	runner := newRunnerWithCommandRunner(fake)

	call, _, err := runner.RunAgyTask("responda apenas: ok", "gemini-3.8-flash-low", "", "smoke-test")
	if err != nil {
		t.Fatalf("RunAgyTask: %v", err)
	}

	if call.Model != "gemini-3.8-flash-low" {
		t.Errorf("Model = %q, want gemini-3.8-flash-low", call.Model)
	}
	if call.Status != "SUCCESS" {
		t.Errorf("Status = %q, want SUCCESS", call.Status)
	}
	if call.InputTokens != 120 || call.OutputTokens != 40 || call.ThinkingTokens != 10 || call.CacheReadTokens != 5 {
		t.Errorf("tokens = %d/%d/%d/%d, want 120/40/10/5",
			call.InputTokens, call.OutputTokens, call.ThinkingTokens, call.CacheReadTokens)
	}
	if call.Source != "agy" {
		t.Errorf("Source = %q, want agy", call.Source)
	}
	if call.Task != "smoke-test" {
		t.Errorf("Task = %q, want smoke-test", call.Task)
	}
	// agy's CLI never reports cache-write/creation — must come through as
	// 0 (unmeasured, not confirmed zero — see metrics.TaskCallSamples'
	// CacheCreationMeasured gauge, which reads call.Source == "agy").
	if call.CacheCreationTokens != 0 {
		t.Errorf("CacheCreationTokens = %d, want 0 (agy never reports this)", call.CacheCreationTokens)
	}
}

func TestRunAgyTask_TaskDefaultsToPromptWhenLabelEmpty(t *testing.T) {
	fake := &fakeCommandRunner{stdout: fakeAgyTaskResponse}
	runner := newRunnerWithCommandRunner(fake)

	call, _, err := runner.RunAgyTask("responda apenas: ok", "gemini-3.8-flash-low", "", "")
	if err != nil {
		t.Fatalf("RunAgyTask: %v", err)
	}
	if call.Task != "responda apenas: ok" {
		t.Errorf("Task = %q, want the prompt itself when no label given", call.Task)
	}
}

func TestRunAgyTask_InvokesExpectedCommandWithEffort(t *testing.T) {
	fake := &fakeCommandRunner{stdout: fakeAgyTaskResponse}
	runner := newRunnerWithCommandRunner(fake)

	if _, _, err := runner.RunAgyTask("hello", "gemini-3.8-flash-low", "high", ""); err != nil {
		t.Fatalf("RunAgyTask: %v", err)
	}

	want := []string{"agy", "-p", "hello", "--model", "gemini-3.8-flash-low", "--output-format", "json", "--effort", "high"}
	if len(fake.gotCmd) != len(want) {
		t.Fatalf("gotCmd = %v, want %v", fake.gotCmd, want)
	}
	for i := range want {
		if fake.gotCmd[i] != want[i] {
			t.Errorf("gotCmd[%d] = %q, want %q", i, fake.gotCmd[i], want[i])
		}
	}
}

func TestRunAgyTask_OmitsEffortFlagWhenNotGiven(t *testing.T) {
	fake := &fakeCommandRunner{stdout: fakeAgyTaskResponse}
	runner := newRunnerWithCommandRunner(fake)

	if _, _, err := runner.RunAgyTask("hello", "gemini-3.8-flash-low", "", ""); err != nil {
		t.Fatalf("RunAgyTask: %v", err)
	}
	for _, a := range fake.gotCmd {
		if a == "--effort" {
			t.Errorf("gotCmd %v should not contain --effort when none was requested", fake.gotCmd)
		}
	}
}
