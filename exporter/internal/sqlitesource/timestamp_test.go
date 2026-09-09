package sqlitesource

import (
	"testing"
	"time"
)

func TestParseTimestamp(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		want    time.Time
		wantErr bool
	}{
		{
			name:  "claude-code millisecond precision with Z suffix",
			input: "2026-09-09T17:32:14.831Z",
			want:  time.Date(2026, 9, 9, 17, 32, 14, 831_000_000, time.UTC),
		},
		{
			name:  "agy/copilot-track microsecond precision with explicit offset",
			input: "2026-09-09T13:50:07.617750+00:00",
			want:  time.Date(2026, 9, 9, 13, 50, 7, 617_750_000, time.UTC),
		},
		{
			name:  "no fractional seconds",
			input: "2026-09-09T13:50:07Z",
			want:  time.Date(2026, 9, 9, 13, 50, 7, 0, time.UTC),
		},
		{
			name:    "empty string",
			input:   "",
			wantErr: true,
		},
		{
			name:    "garbage",
			input:   "not-a-timestamp",
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseTimestamp(tt.input)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("expected error, got %v", got)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !got.Equal(tt.want) {
				t.Errorf("got %v, want %v", got, tt.want)
			}
		})
	}
}
