---
name: agy-tracking
description: "Track and display agy (Google Antigravity CLI) token/quota usage. Use when the user asks about token consumption, weekly quota, or agy usage stats."
---

# agy Token Tracking

Data lives in a local append-only store (`~/.local/share/ai-tokens-tracker/tsdb/`, not SQLite —
never the agy binary's own internal SQLite either, that one is undocumented protobuf and not
touched by this tool). See `docs/madrs/` in this repo for why (MADR-003, MADR-004).

Three kinds of data, read directly from local sources by `exporter/internal/adapters/*` (no
Python, no intermediate database — see `docs/madrs/MADR-004`):
- **Weekly quota snapshots** — zero-cost `/usage` polls, one sample per model group per poll.
  Covers all agy account usage, TUI included.
- **Task calls** — real token counts from individual `-p` calls made via `agytrack`/`copilottrack`.
  Covers only calls made through those wrappers, not TUI usage.
- **Claude Code / Copilot events** — real token counts per request/session, read from local
  transcripts (`~/.claude/projects/**/*.jsonl`, `~/.copilot/session-state/**/events.jsonl`).
  Zero-cost, covers interactive/non-interactive sessions and subagents (Task/Agent tool,
  Workflow tool). Subagent events share their parent session's `session_id` (no session of their
  own) but carry a distinct `agent_id` for `isSidechain: true` records.

Exposed as Prometheus metrics (`aitokens_tokens_total` with a `token_type` label, plus
`aitokens_quota_remaining_ratio`) — see `exporter/internal/metrics` for the mapping, and
`docs/madrs/MADR-003` for the label cardinality rationale.

## Commands

- `curl http://127.0.0.1:9464/metrics` — current-state metrics, Prometheus text format (requires
  `ai-tokens-exporter.service` running — see `systemd/README.md`)
- `xdg-open http://127.0.0.1:8428/vmui/` — PromQL ad-hoc queries (requires VictoriaMetrics)
- `xdg-open http://127.0.0.1:8080/projects/ai-tokens-tracker/dashboards/ai-tokens` — versioned
  dashboard (requires Perses)
- `bash bin/agytrack --model <model> --task "<label>" "<prompt>"` — run a tracked agy task call
- `bash bin/copilottrack --model <model> --task "<label>" "<prompt>"` — run a tracked Copilot
  task call
- `bash bin/agydelegate --complexity <low|medium|high> --task "<label>" "<prompt>"` — delegate a
  task to agy, auto-picking the model by complexity + remaining quota

Each of the three `bin/*` commands falls back to `go run` if `exporter/bin/aitokens-exporter`
isn't installed yet — `cd exporter && make install` avoids that overhead on every call.

For continuous, hands-off collection (no need to run the commands above manually), install the
systemd user units — see `systemd/README.md`.

**No more ad-hoc comparison by arbitrary time window/session** — the HTML dashboard that offered
this was removed along with SQLite (MADR-004). `session_name` (named sessions via `claude -n
<name>`) covers named A/B comparison in the `experiments` dashboard, but not free comparison by
timestamp.
