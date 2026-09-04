#!/usr/bin/env python3
"""Generate a standalone HTML report to compare token usage across time windows.

Usage:
    token-compare-report.py [--out report.html]

Reads every tracked source through core.usage.collect_usage_events (source-
agnostic — Claude Code, agy tracked calls, and any future adapter that
produces UsageEvent) plus agy's quota snapshots, embeds them as JSON in a
static HTML file, and opens it in the default browser. All comparison happens
client-side: pick two or more date ranges directly in the page (e.g. "used
recall-search Sep 1-3" vs "baseline Sep 4-6") and the page computes totals,
per-request averages, cache-hit rate, and per-model/per-source breakdowns for
each range — nothing about the ranges is stored, they're just a lens over
data collected the normal way (claude-code-snapshot.py, agy-snapshot.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.sqlite_usage_store import SqliteUsageStore
from core.usage import collect_usage_events

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>token usage — compare windows</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js"
        integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"
        crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"
        integrity="sha384-cVMg8E3QFwTvGCDuK+ET4PD341jF3W8nO1auiXfuZNQkzbUUiBGLsIQUE+b1mxws"
        crossorigin="anonymous"></script>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: Canvas; color: CanvasText; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  h2 { font-size: 13px; margin: 0 0 12px; font-weight: 600; }
  .sub { color: GrayText; font-size: 13px; margin-bottom: 24px; }
  .empty { color: GrayText; font-size: 14px; padding: 40px 0; text-align: center; }
  .card { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 8px; padding: 16px; margin-bottom: 24px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent); }
  th { color: GrayText; font-weight: 500; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  button { font: inherit; padding: 4px 10px; cursor: pointer; }
  input[type=date] { font: inherit; padding: 3px 6px; }
  input[type=text] { font: inherit; padding: 3px 6px; width: 140px; }

  .ranges { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
  .range-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .range-row .swatch { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .range-row .remove { margin-left: auto; color: GrayText; background: none; border: none; }

  .compare-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
  .metric-card { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 8px; padding: 14px; }
  .metric-card .name { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 13px; margin-bottom: 10px; }
  .metric-card .swatch { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .metric-card dl { margin: 0; display: grid; grid-template-columns: auto auto; gap: 4px 12px; font-size: 13px; }
  .metric-card dt { color: GrayText; }
  .metric-card dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }

  .breakdown-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
</style>
</head>
<body>
<h1>token usage — compare windows</h1>
<div class="sub" id="generated-at"></div>

<div id="content"></div>

<script>
const EVENTS = __EVENTS__;
const SNAPSHOTS = __SNAPSHOTS__;
const PALETTE = ["#7aa2f7", "#9ece6a", "#e0af68", "#f7768e", "#bb9af7", "#7dcfff"];

document.getElementById("generated-at").textContent =
  `${EVENTS.length} tracked requests · ${SNAPSHOTS.length} agy quota snapshots · generated ${new Date().toLocaleString()}`;

if (EVENTS.length === 0 && SNAPSHOTS.length === 0) {
  document.getElementById("content").innerHTML =
    '<p class="empty">No data yet. Run claude-code-snapshot.py and/or agy-snapshot.py to start collecting.</p>';
} else {
  init();
}

function allTimestamps() {
  return [...EVENTS.map(e => e.timestamp), ...SNAPSHOTS.map(s => s.timestamp)].sort();
}

function toDateInput(ts) {
  return ts.slice(0, 10);
}

let ranges = [];
let nextId = 1;

function defaultRanges() {
  const ts = allTimestamps();
  if (ts.length === 0) return [];
  const days = [...new Set(ts.map(toDateInput))].sort();
  if (days.length === 1) {
    return [{ id: nextId++, label: "range 1", from: days[0], to: days[0] }];
  }
  const mid = Math.floor(days.length / 2);
  return [
    { id: nextId++, label: "range 1", from: days[0], to: days[mid - 1] },
    { id: nextId++, label: "range 2", from: days[mid], to: days[days.length - 1] },
  ];
}

function init() {
  ranges = defaultRanges();
  const content = document.getElementById("content");
  content.innerHTML = `
    <div class="card">
      <h2>Timeline (drag a selection, or edit ranges below)</h2>
      <canvas id="timeline-chart" height="80"></canvas>
    </div>
    <div class="card">
      <h2>Ranges to compare</h2>
      <div class="ranges" id="ranges-list"></div>
      <button id="add-range">+ add range</button>
    </div>
    <div class="card">
      <h2>Comparison</h2>
      <div class="compare-grid" id="compare-grid"></div>
    </div>
    <div class="breakdown-grid">
      <div class="card"><h2>Total tokens by model</h2><canvas id="model-chart"></canvas></div>
      <div class="card"><h2>Total tokens by source</h2><canvas id="source-chart"></canvas></div>
    </div>
  `;
  document.getElementById("add-range").addEventListener("click", () => {
    const ts = allTimestamps();
    const last = ts.length ? toDateInput(ts[ts.length - 1]) : new Date().toISOString().slice(0, 10);
    ranges.push({ id: nextId++, label: `range ${ranges.length + 1}`, from: last, to: last });
    renderAll();
  });
  renderTimeline();
  renderAll();
}

function groupBy(arr, keyFn) {
  const out = new Map();
  for (const item of arr) {
    const k = keyFn(item);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(item);
  }
  return out;
}

function renderTimeline() {
  const byDay = groupBy(EVENTS, e => toDateInput(e.timestamp));
  const days = [...byDay.keys()].sort();
  const data = days.map(d => byDay.get(d).reduce((s, e) => s + e.total_tokens, 0));
  new Chart(document.getElementById("timeline-chart"), {
    type: "line",
    data: {
      labels: days,
      datasets: [{
        label: "Total tokens/day",
        data,
        borderColor: PALETTE[0],
        backgroundColor: PALETTE[0],
        tension: 0.25,
        pointRadius: 3,
        fill: false,
      }],
    },
    options: { plugins: { legend: { display: false } } },
  });
}

function inRange(ts, range) {
  const d = toDateInput(ts);
  return d >= range.from && d <= range.to;
}

function eventsInRange(range) {
  return EVENTS.filter(e => inRange(e.timestamp, range));
}

function renderRangesList() {
  const list = document.getElementById("ranges-list");
  list.replaceChildren(...ranges.map((r, i) => {
    const row = document.createElement("div");
    row.className = "range-row";

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = PALETTE[i % PALETTE.length];
    row.appendChild(swatch);

    const label = document.createElement("input");
    label.type = "text";
    label.value = r.label;
    label.addEventListener("input", () => { r.label = label.value; renderCompare(); });
    row.appendChild(label);

    const from = document.createElement("input");
    from.type = "date";
    from.value = r.from;
    from.addEventListener("change", () => { r.from = from.value; renderCompare(); renderBreakdowns(); });
    row.appendChild(from);

    const to = document.createElement("input");
    to.type = "date";
    to.value = r.to;
    to.addEventListener("change", () => { r.to = to.value; renderCompare(); renderBreakdowns(); });
    row.appendChild(to);

    const remove = document.createElement("button");
    remove.className = "remove";
    remove.textContent = "remove";
    remove.addEventListener("click", () => { ranges.splice(i, 1); renderAll(); });
    row.appendChild(remove);

    return row;
  }));
}

function quotaConsumedInRange(range) {
  const byGroup = groupBy(SNAPSHOTS, s => s.model_group);
  let consumed = 0;
  for (const rows of byGroup.values()) {
    const inWindow = rows.filter(s => inRange(s.timestamp, range)).sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    if (inWindow.length < 2) continue;
    const first = inWindow[0].remaining_fraction;
    const last = inWindow[inWindow.length - 1].remaining_fraction;
    consumed += Math.max(0, first - last);
  }
  return consumed;
}

function renderCompare() {
  const grid = document.getElementById("compare-grid");
  grid.replaceChildren(...ranges.map((r, i) => {
    const events = eventsInRange(r);
    const totalTokens = events.reduce((s, e) => s + e.total_tokens, 0);
    const inputTokens = events.reduce((s, e) => s + e.input_tokens, 0);
    const cacheRead = events.reduce((s, e) => s + e.cache_read_tokens, 0);
    const cacheHitRate = (inputTokens + cacheRead) > 0 ? cacheRead / (inputTokens + cacheRead) : 0;
    const sessions = new Set(events.map(e => e.session_id).filter(Boolean)).size;
    const quota = quotaConsumedInRange(r);

    const card = document.createElement("div");
    card.className = "metric-card";
    card.innerHTML = `
      <div class="name"><span class="swatch" style="background:${PALETTE[i % PALETTE.length]}"></span>${escapeHtml(r.label)}</div>
      <dl>
        <dt>Requests</dt><dd>${events.length.toLocaleString()}</dd>
        <dt>Sessions</dt><dd>${sessions.toLocaleString()}</dd>
        <dt>Total tokens</dt><dd>${totalTokens.toLocaleString()}</dd>
        <dt>Tokens/request</dt><dd>${events.length ? Math.round(totalTokens / events.length).toLocaleString() : "–"}</dd>
        <dt>Cache-hit rate</dt><dd>${(cacheHitRate * 100).toFixed(1)}%</dd>
        <dt>agy quota consumed</dt><dd>${(quota * 100).toFixed(1)}%</dd>
      </dl>
    `;
    return card;
  }));
}

let modelChart = null;
let sourceChart = null;

function renderBreakdowns() {
  const labels = ranges.map(r => r.label);

  const models = [...new Set(EVENTS.map(e => e.model))];
  const modelDatasets = models.map((m, i) => ({
    label: m,
    data: ranges.map(r => eventsInRange(r).filter(e => e.model === m).reduce((s, e) => s + e.total_tokens, 0)),
    backgroundColor: PALETTE[i % PALETTE.length],
  }));
  if (modelChart) modelChart.destroy();
  modelChart = new Chart(document.getElementById("model-chart"), {
    type: "bar",
    data: { labels, datasets: modelDatasets },
    options: { responsive: true, scales: { x: { stacked: true }, y: { stacked: true } } },
  });

  const sources = [...new Set(EVENTS.map(e => e.source))];
  const sourceDatasets = sources.map((src, i) => ({
    label: src,
    data: ranges.map(r => eventsInRange(r).filter(e => e.source === src).reduce((s, e) => s + e.total_tokens, 0)),
    backgroundColor: PALETTE[i % PALETTE.length],
  }));
  if (sourceChart) sourceChart.destroy();
  sourceChart = new Chart(document.getElementById("source-chart"), {
    type: "bar",
    data: { labels, datasets: sourceDatasets },
    options: { responsive: true, scales: { x: { stacked: true }, y: { stacked: true } } },
  });
}

function renderAll() {
  renderRangesList();
  renderCompare();
  renderBreakdowns();
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
</script>
</body>
</html>
"""


def _json_for_script(data: object) -> str:
    """json.dumps, but safe to embed inside a <script> tag — escapes '</' so a
    value containing '</script>' can't prematurely close the tag."""
    return json.dumps(data).replace("</", "<\\/")


def fetch_data() -> tuple[list[dict], list[dict]]:
    store = SqliteUsageStore()
    try:
        events = [
            {
                "source": e.source,
                "timestamp": e.timestamp,
                "model": e.model,
                "session_id": e.session_id,
                "project": e.project,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "cache_read_tokens": e.cache_read_tokens,
                "cache_creation_tokens": e.cache_creation_tokens,
                "total_tokens": e.total_tokens,
            }
            for e in collect_usage_events(store)
        ]
        snapshots = [
            {
                "timestamp": s.timestamp,
                "model_group": s.model_group,
                "remaining_fraction": s.remaining_fraction,
                "reset_time": s.reset_time,
            }
            for s in store.list_snapshots()
        ]
        return events, snapshots
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=None, help="Output path (default: ~/.cache/ai-tokens-tracker/compare-report.html)")
    parser.add_argument("--no-open", action="store_true", help="Don't open the report in a browser")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else Path.home() / ".cache" / "ai-tokens-tracker" / "compare-report.html"
    out_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    events, snapshots = fetch_data()
    html = TEMPLATE.replace("__EVENTS__", _json_for_script(events)).replace(
        "__SNAPSHOTS__", _json_for_script(snapshots)
    )
    out_path.write_text(html)
    out_path.chmod(0o600)

    print(f"✓ report written to {out_path}")
    if not args.no_open:
        webbrowser.open(f"file://{out_path}")


if __name__ == "__main__":
    main()
