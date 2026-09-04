---
name: agy-tracking
description: "Track and display agy (Google Antigravity CLI) token/quota usage. Use when the user asks about token consumption, weekly quota, or agy usage stats."
---

# agy Token Tracking

Data lives in a local SQLite database (`~/.local/share/ai-tokens-tracker/usage.db` by default, or
`$AGY_TOOL_DB` if set) — never JSONL, never the agy binary's own internal SQLite (that one is
undocumented protobuf and not touched by this tool). See `docs/madrs/` in this repo for why.

Three kinds of data:
- **Weekly quota snapshots** (`usage_snapshots` table) — zero-cost `/usage` polls, one row per
  model group per poll. Covers all agy account usage, TUI included.
- **Task calls** (`task_calls` table) — real token counts from individual `-p` calls made via
  `scripts/agy-track.py`. Covers only calls made through that wrapper, not TUI usage.
- **Claude Code events** (`claude_code_usage_events` table) — real token counts per request,
  read from local transcripts (`~/.claude/projects/**/*.jsonl`). Zero-cost, covers all Claude
  Code usage (interactive and non-interactive alike).

`core/usage.collect_usage_events` normalizes Claude Code events and agy task calls into one
tool-agnostic `UsageEvent` shape — reports/dashboards read that, not the raw per-tool tables.

## Commands

- `bash bin/agystatus` — generate and open an HTML report (charts + recent calls table)
- `bash bin/agysnapshot` — record one quota snapshot now (normally run on a timer)
- `bash bin/claudecodesnapshot` — record new Claude Code events now (normally run on a timer)
- `bash bin/tokencompare` — generate and open a static HTML comparing token usage across
  freely-picked time ranges, second-level precision, compared in raw UTC (e.g. a morning session
  with a RAG skill on vs. an afternoon session without, same day)
- `bash bin/tokendashboard` — same comparison, but as a live local server (auto-refreshes,
  needs `uv sync` once — the only command here with external dependencies)
- `bash bin/agywidget` — launch the GTK always-on-top widget (Linux desktop only)
- `python3 scripts/agy-track.py --model <model> --task "<label>" "<prompt>"` — run a tracked task call
- `bash bin/agydelegate --complexity <low|medium|high> --task "<label>" "<prompt>"` — delegate a
  task to agy, auto-picking the model by complexity + remaining quota (see the `agy-delegate`
  skill in `goriok/my-skills` for when to use this)

For continuous, hands-off collection (no need to run the commands above manually), install the
systemd user units in `systemd/` — see `systemd/README.md`.
