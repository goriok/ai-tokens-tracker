package model

import (
	"fmt"
	"time"
)

// ParseTimestamp handles the ISO-8601 shapes seen across sources:
// "...831Z" (claude-code, ms precision) and "...805841+00:00"
// (agy/copilot-track, µs precision with explicit offset). RFC3339Nano
// covers both — its fractional-second digits are elastic, and it accepts
// both "Z" and numeric offsets. Shared by every transcript/CLI adapter so
// there's one parser, not one per source.
func ParseTimestamp(s string) (time.Time, error) {
	if s == "" {
		return time.Time{}, fmt.Errorf("empty timestamp")
	}
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return time.Time{}, fmt.Errorf("parse timestamp %q: %w", s, err)
	}
	return t, nil
}
