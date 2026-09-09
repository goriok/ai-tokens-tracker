package sqlitesource

import (
	"fmt"
	"time"
)

// parseTimestamp handles the three ISO-8601 shapes seen in the shared TEXT
// column across sources: "...831Z" (claude-code, ms precision), and
// "...805841+00:00" (agy/copilot-track, µs precision with explicit offset).
// time.RFC3339Nano covers both — Go's reference layout's fractional-second
// digits are elastic, and it accepts both "Z" and numeric offsets.
func parseTimestamp(s string) (time.Time, error) {
	if s == "" {
		return time.Time{}, fmt.Errorf("empty timestamp")
	}
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return time.Time{}, fmt.Errorf("parse timestamp %q: %w", s, err)
	}
	return t, nil
}
