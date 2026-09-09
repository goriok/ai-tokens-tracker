package agycli

import (
	"testing"
)

// fakeCommandRunner is the seam: it stands in for the real `agy` subprocess
// invocation. FetchQuota's logic (parsing the JSON response into
// UsageSnapshots) is tested against this without ever spawning a real
// process — the real binary is only exercised in manual live verification
// (see the runner's package doc), the same discipline used for every other
// adapter in this exporter.
type fakeCommandRunner struct {
	stdout string
	err    error
	gotCmd []string // records the exact argv passed, so a test can assert on it
}

func (f *fakeCommandRunner) Run(argv []string) (stdout string, err error) {
	f.gotCmd = argv
	return f.stdout, f.err
}

// realAgyUsageResponse is the actual stdout of `agy -p "/usage"
// --output-format json` on this machine, captured live — a zero-cost
// meta-command (usage.total_tokens: 0 in agy's own response), so safe to
// have run for real once to get this fixture.
const realAgyUsageResponse = `{"conversation_id":"","status":"SUCCESS","response":"Gemini Models\tWeekly Limit Remaining\t0%\t2026-09-11T21:16:10Z\nClaude and GPT models\tWeekly Limit Remaining\t0%\t2026-09-15T20:11:15Z\n","duration_seconds":0,"num_turns":0,"usage":{"input_tokens":0,"output_tokens":0,"thinking_tokens":0,"cache_read_tokens":0,"total_tokens":0},"command":{"name":"usage","data":{"description":"Within each group, models share a weekly limit. Quota is consumed proportionally to the cost of the tokens. Thus, limits will last longer with shorter tasks or using more cost-effective models. Your weekly limit is tied directly to your individual tier.","groups":[{"name":"Gemini Models","description":"Models within this group: Gemini Flash, Gemini Pro","buckets":[{"id":"gemini-weekly","name":"Weekly Limit Remaining","description":"You have hit your weekly limit, it refreshes in 2 days, 1 hour. If on a supported paid plan, you can use AI credits in the interim or upgrade to a higher tier.","window":"weekly","remaining_fraction":0,"reset_time":"2026-09-11T21:16:10Z"}]},{"name":"Claude and GPT models","description":"Models within this group: Claude Opus, Claude Sonnet, GPT-OSS","buckets":[{"id":"3p-weekly","name":"Weekly Limit Remaining","description":"You have hit your weekly limit, it refreshes in 6 days. If on a supported paid plan, you can use AI credits in the interim or upgrade to a higher tier.","window":"weekly","remaining_fraction":0,"reset_time":"2026-09-15T20:11:15Z"}]}]}}}`

func TestFetchQuota_ParsesRealAgyResponseShape(t *testing.T) {
	fake := &fakeCommandRunner{stdout: realAgyUsageResponse}
	runner := newRunnerWithCommandRunner(fake)

	snapshots, err := runner.FetchQuota()
	if err != nil {
		t.Fatalf("FetchQuota: %v", err)
	}

	if len(snapshots) != 2 {
		t.Fatalf("len(snapshots) = %d, want 2 (one bucket per group)", len(snapshots))
	}

	if snapshots[0].ModelGroup != "Gemini Models" {
		t.Errorf("snapshots[0].ModelGroup = %q, want Gemini Models", snapshots[0].ModelGroup)
	}
	if snapshots[0].RemainingFraction != 0 {
		t.Errorf("snapshots[0].RemainingFraction = %v, want 0", snapshots[0].RemainingFraction)
	}
	if snapshots[0].ResetTime != "2026-09-11T21:16:10Z" {
		t.Errorf("snapshots[0].ResetTime = %q, want 2026-09-11T21:16:10Z", snapshots[0].ResetTime)
	}

	if snapshots[1].ModelGroup != "Claude and GPT models" {
		t.Errorf("snapshots[1].ModelGroup = %q, want Claude and GPT models", snapshots[1].ModelGroup)
	}

	// Every snapshot should carry (roughly) the same poll timestamp — this
	// runner assigns "now" once per FetchQuota call, not once per bucket.
	if snapshots[0].Timestamp.IsZero() || snapshots[1].Timestamp.IsZero() {
		t.Error("expected both snapshots to have a non-zero Timestamp")
	}
}

func TestFetchQuota_InvokesTheExpectedCommand(t *testing.T) {
	fake := &fakeCommandRunner{stdout: realAgyUsageResponse}
	runner := newRunnerWithCommandRunner(fake)

	if _, err := runner.FetchQuota(); err != nil {
		t.Fatalf("FetchQuota: %v", err)
	}

	want := []string{"agy", "-p", "/usage", "--output-format", "json"}
	if len(fake.gotCmd) != len(want) {
		t.Fatalf("gotCmd = %v, want %v", fake.gotCmd, want)
	}
	for i := range want {
		if fake.gotCmd[i] != want[i] {
			t.Errorf("gotCmd[%d] = %q, want %q", i, fake.gotCmd[i], want[i])
		}
	}
}
