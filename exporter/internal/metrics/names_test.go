package metrics

import "testing"

func TestAgentKind(t *testing.T) {
	tests := []struct {
		agentID string
		want    string
	}{
		{"", AgentKindMain},
		{"agent-xyz", AgentKindSub},
	}
	for _, tt := range tests {
		if got := AgentKind(tt.agentID); got != tt.want {
			t.Errorf("AgentKind(%q) = %q, want %q", tt.agentID, got, tt.want)
		}
	}
}

func TestSlugifyModelGroup(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"Gemini Models", "gemini_models"},
		{"Claude and GPT models", "claude_and_gpt_models"},
		{"already_slug", "already_slug"},
		{"  Leading/Trailing  ", "leading_trailing"},
	}
	for _, tt := range tests {
		if got := SlugifyModelGroup(tt.input); got != tt.want {
			t.Errorf("SlugifyModelGroup(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}
