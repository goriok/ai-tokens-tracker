#!/usr/bin/env python3
"""Generate a standalone HTML report to compare token usage across time windows.

Usage:
    token-compare-report.py [--out report.html]

Reads every tracked source through core.usage.collect_usage_events (source-
agnostic — Claude Code, agy tracked calls, and any future adapter that
produces UsageEvent) plus agy's quota snapshots, embeds them as JSON in a
static HTML file, and opens it in the default browser. All comparison happens
client-side: pick two or more time ranges directly in the page, second-level
precision, compared in raw UTC (e.g. "used recall-search 9am-noon" vs
"baseline noon-3pm", same day) and the page computes totals, per-request
averages, cache-hit rate, and per-model/per-source breakdowns for each range
— nothing about the ranges is stored, they're just a lens over data collected
the normal way (claude-code-snapshot.py, agy-snapshot.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.sqlite_usage_store import SqliteUsageStore
from core.usage import build_dashboard_payload

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
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"
        integrity="sha384-Cs3dgUx6+jDxxuqHvVH8Onpyj2LF1gKZurLDlhqzuJmUqVYMJ0THTWpxK5Z086Zm"
        crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js"
        integrity="sha384-dwwI6ICEN/0ZQlS5owhUa/6ZzvwUPmjH45bFVCAcjgjTulbHJvlE+TGU3g1k0N3R"
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
  input[type=datetime-local] { font: inherit; padding: 3px 6px; }
  input[type=text] { font: inherit; padding: 3px 6px; width: 140px; }
  select { font: inherit; padding: 3px 6px; max-width: 160px; }

  .global-window-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
  .global-window-row label { display: flex; align-items: center; gap: 4px; }
  .ranges { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
  .range-row { display: flex; flex-direction: column; gap: 6px; padding-bottom: 10px; border-bottom: 1px solid color-mix(in srgb, CanvasText 8%, transparent); }
  .range-row .row-identity, .range-row .row-period { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .range-row .swatch { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .range-row .remove { margin-left: auto; color: GrayText; background: none; border: none; }

  .compare-chart { margin-bottom: 16px; }
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
const SESSION_TITLES = __SESSION_TITLES__;
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

function toDateTimeInput(ts) {
  // UTC, no timezone conversion — what you type is what's compared.
  return ts.slice(0, 19);
}

function toDateInput(ts) {
  return ts.slice(0, 10);
}

let ranges = [];
let nextId = 1;
let globalWindow = { enabled: true, from: "", to: "" };

function mostRecentNamedRuns(count) {
  return namedRuns()
    .map(r => ({ ...r, bounds: timestampBoundsForRun(r) }))
    .filter(r => r.bounds !== null)
    .sort((a, b) => b.bounds.to.localeCompare(a.bounds.to))
    .slice(0, count);
}

function defaultWindow() {
  const now = new Date();
  const yesterday = new Date(now); yesterday.setUTCDate(now.getUTCDate() - 1);
  const tomorrow = new Date(now); tomorrow.setUTCDate(now.getUTCDate() + 1);
  return {
    from: yesterday.toISOString().slice(0, 10) + "T00:00:00",
    to: tomorrow.toISOString().slice(0, 10) + "T23:59:59",
  };
}

function defaultRanges() {
  const recentRuns = mostRecentNamedRuns(2);
  if (recentRuns.length >= 2) {
    return recentRuns
      .slice()
      .reverse()
      .map(r => ({ id: nextId++, label: r.title, from: r.bounds.from, to: r.bounds.to }));
  }

  if (allTimestamps().length === 0) return [];
  const { from, to } = defaultWindow();
  return [
    { id: nextId++, label: "range 1", from, to },
    { id: nextId++, label: "range 2", from, to },
  ];
}

function init() {
  if (globalWindow.enabled && !globalWindow.from && !globalWindow.to) {
    const { from, to } = defaultWindow();
    globalWindow.from = from;
    globalWindow.to = to;
  }
  ranges = defaultRanges();
  const content = document.getElementById("content");
  content.innerHTML = `
    <div class="card">
      <h2>Timeline</h2>
      <canvas id="timeline-chart" height="40"></canvas>
    </div>
    <div class="card">
      <h2>Ranges to compare</h2>
      <div class="global-window-row">
        <label><input type="checkbox" id="global-window-toggle"> global window</label>
        <input type="datetime-local" step="1" id="global-window-from" hidden>
        <span id="global-window-arrow" hidden>→</span>
        <input type="datetime-local" step="1" id="global-window-to" hidden>
      </div>
      <div class="ranges" id="ranges-list"></div>
      <button id="add-range">+ add range</button>
      <datalist id="known-runs"></datalist>
    </div>
    <div class="card">
      <h2>Comparison</h2>
      <canvas id="compare-chart" class="compare-chart" height="70"></canvas>
      <div class="compare-grid" id="compare-grid"></div>
    </div>
    <div class="breakdown-grid">
      <div class="card"><h2>Total tokens by model</h2><canvas id="model-chart"></canvas></div>
      <div class="card"><h2>Total tokens by source</h2><canvas id="source-chart"></canvas></div>
    </div>
  `;
  document.getElementById("add-range").addEventListener("click", () => {
    const ts = allTimestamps();
    const last = ts.length ? toDateTimeInput(ts[ts.length - 1]) : new Date().toISOString().slice(0, 19);
    ranges.push({ id: nextId++, label: `range ${ranges.length + 1}`, from: last, to: last });
    renderAll();
  });

  const gwToggle = document.getElementById("global-window-toggle");
  const gwFrom = document.getElementById("global-window-from");
  const gwArrow = document.getElementById("global-window-arrow");
  const gwTo = document.getElementById("global-window-to");
  gwToggle.checked = globalWindow.enabled;
  gwFrom.value = globalWindow.from;
  gwTo.value = globalWindow.to;
  [gwFrom, gwArrow, gwTo].forEach(el => { el.hidden = !globalWindow.enabled; });
  gwToggle.addEventListener("change", () => {
    globalWindow.enabled = gwToggle.checked;
    if (globalWindow.enabled && !globalWindow.from && !globalWindow.to) {
      const { from, to } = defaultWindow();
      globalWindow.from = from;
      globalWindow.to = to;
      gwFrom.value = from;
      gwTo.value = to;
    }
    [gwFrom, gwArrow, gwTo].forEach(el => { el.hidden = !globalWindow.enabled; });
    renderAll();
  });
  gwFrom.addEventListener("change", () => { globalWindow.from = gwFrom.value; renderAll(); });
  gwTo.addEventListener("change", () => { globalWindow.to = gwTo.value; renderAll(); });

  renderTimeline();
  renderAll();
}

// Splits a label like "A1" into group "A" and position 1, so ranges can be
// colored by group (not creation order) and charted paired by position.
// Falls back to the whole label as its own group when there's no trailing
// number (e.g. a free-text label typed by hand).
function parseLabel(label) {
  const m = /^(.*?)(\\d+)$/.exec(label || "");
  if (!m) return { group: label || "", position: null };
  return { group: m[1], position: parseInt(m[2], 10) };
}

function colorForLabel(label) {
  const { group } = parseLabel(label);
  const groups = [...new Set(ranges.map(r => parseLabel(r.label).group))];
  const idx = groups.indexOf(group);
  return PALETTE[(idx < 0 ? 0 : idx) % PALETTE.length];
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

let timelineChart = null;

function renderTimeline() {
  const byDay = groupBy(EVENTS, e => toDateInput(e.timestamp));
  const days = [...byDay.keys()].sort();
  const points = days.map(d => ({ x: d + "T12:00:00Z", y: byDay.get(d).reduce((s, e) => s + e.total_tokens, 0) }));
  if (timelineChart) timelineChart.destroy();
  timelineChart = new Chart(document.getElementById("timeline-chart"), {
    type: "line",
    data: {
      datasets: [{
        label: "Total tokens/day",
        data: points,
        borderColor: PALETTE[0],
        backgroundColor: PALETTE[0],
        tension: 0.25,
        pointRadius: 3,
        fill: false,
      }],
    },
    options: {
      plugins: {
        legend: { display: false },
        zoom: {
          zoom: {
            drag: { enabled: true },
            mode: "x",
            onZoomComplete: ({ chart }) => {
              const { min, max } = chart.scales.x;
              globalWindow.enabled = true;
              globalWindow.from = toDateTimeInput(new Date(min).toISOString());
              globalWindow.to = toDateTimeInput(new Date(max).toISOString());
              chart.resetZoom();
              const gwToggle = document.getElementById("global-window-toggle");
              const gwFrom = document.getElementById("global-window-from");
              const gwArrow = document.getElementById("global-window-arrow");
              const gwTo = document.getElementById("global-window-to");
              gwToggle.checked = true;
              gwFrom.value = globalWindow.from;
              gwTo.value = globalWindow.to;
              [gwFrom, gwArrow, gwTo].forEach(el => { el.hidden = false; });
              renderAll();
            },
          },
        },
      },
      scales: { x: { type: "time", time: { unit: "day" } } },
    },
  });
}

function inRange(ts, range) {
  const t = toDateTimeInput(ts);
  return t >= range.from && t <= range.to;
}

function inGlobalWindow(ts) {
  if (!globalWindow.enabled) return true;
  const t = toDateTimeInput(ts);
  return (!globalWindow.from || t >= globalWindow.from) && (!globalWindow.to || t <= globalWindow.to);
}

// In global-window mode, a range no longer carries its own from/to — it's
// just a label. If the label matches one specific session/agy run (exact
// title), scope to that run's events (still clipped to the global window);
// an unmatched free-text label falls back to "everything in the window"
// (e.g. a "baseline: all" range next to specific-run ranges). No group
// aggregation — each range is always one run, comparisons stay per-session.
function eventsInRange(range) {
  if (globalWindow.enabled) {
    const run = namedRuns().find(r => r.title === range.label);
    const pool = run ? run.events : EVENTS;
    return pool.filter(e => inGlobalWindow(e.timestamp));
  }
  return EVENTS.filter(e => inRange(e.timestamp, range));
}

// Unifies two ways a run can be named: a Claude Code session's custom
// title (N events share it) and an agy TaskCall's --task label (1 event =
// 1 label). Each becomes a { key, title, events } entry so the range
// picker doesn't need to know which kind it's choosing between.
function namedRuns() {
  const bySession = SESSION_TITLES.map(t => ({
    key: `session:${t.session_id}`,
    title: t.title,
    events: EVENTS.filter(e => e.session_id === t.session_id),
  }));
  const agyLabels = [...new Set(EVENTS.filter(e => e.source === "agy" && e.label).map(e => e.label))];
  const byLabel = agyLabels.map(label => ({
    key: `label:${label}`,
    title: label,
    events: EVENTS.filter(e => e.source === "agy" && e.label === label),
  }));
  return [...bySession, ...byLabel]
    .filter(r => r.events.length > 0)
    .sort((a, b) => a.title.localeCompare(b.title));
}

function timestampBoundsForRun(run) {
  const ts = run.events.map(e => e.timestamp).sort();
  if (ts.length === 0) return null;
  return { from: toDateTimeInput(ts[0]), to: toDateTimeInput(ts[ts.length - 1]) };
}

function renderRangesList() {
  const list = document.getElementById("ranges-list");
  const runs = namedRuns();
  const datalistId = "known-runs";
  const datalist = document.getElementById(datalistId);
  if (datalist) {
    datalist.replaceChildren(...runs.map(run => {
      const opt = document.createElement("option");
      opt.value = run.title;
      return opt;
    }));
  }
  list.replaceChildren(...ranges.map((r, i) => {
    const row = document.createElement("div");
    row.className = "range-row";

    const identity = document.createElement("div");
    identity.className = "row-identity";

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = colorForLabel(r.label);
    identity.appendChild(swatch);

    const label = document.createElement("input");
    label.type = "text";
    label.value = r.label;
    label.setAttribute("list", datalistId);
    label.placeholder = "label or session/run name";
    label.addEventListener("input", () => { r.label = label.value; renderCompareChart(); renderCompare(); });
    label.addEventListener("change", () => {
      const run = runs.find(x => x.title === label.value);
      if (!run) return;
      const bounds = timestampBoundsForRun(run);
      if (!bounds) return;
      r.from = bounds.from;
      r.to = bounds.to;
      renderAll();
    });
    identity.appendChild(label);

    const remove = document.createElement("button");
    remove.className = "remove";
    remove.textContent = "remove";
    remove.addEventListener("click", () => { ranges.splice(i, 1); renderAll(); });
    identity.appendChild(remove);

    row.appendChild(identity);

    if (!globalWindow.enabled) {
      const period = document.createElement("div");
      period.className = "row-period";

      const from = document.createElement("input");
      from.type = "datetime-local";
      from.step = "1";
      from.value = r.from;
      from.addEventListener("change", () => { r.from = from.value; renderCompareChart(); renderCompare(); renderBreakdowns(); });
      period.appendChild(from);

      const arrow = document.createElement("span");
      arrow.textContent = "→";
      arrow.style.color = "GrayText";
      period.appendChild(arrow);

      const to = document.createElement("input");
      to.type = "datetime-local";
      to.step = "1";
      to.value = r.to;
      to.addEventListener("change", () => { r.to = to.value; renderCompareChart(); renderCompare(); renderBreakdowns(); });
      period.appendChild(to);

      row.appendChild(period);
    }

    return row;
  }));
}

function quotaConsumedInRange(range) {
  const matches = globalWindow.enabled
    ? s => inGlobalWindow(s.timestamp)
    : s => inRange(s.timestamp, range);
  const byGroup = groupBy(SNAPSHOTS, s => s.model_group);
  let consumed = 0;
  for (const rows of byGroup.values()) {
    const inWindow = rows.filter(matches).sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    if (inWindow.length < 2) continue;
    const first = inWindow[0].remaining_fraction;
    const last = inWindow[inWindow.length - 1].remaining_fraction;
    consumed += Math.max(0, first - last);
  }
  return consumed;
}

function computeRangeMetrics(range) {
  const events = eventsInRange(range);
  const totalTokens = events.reduce((s, e) => s + e.total_tokens, 0);
  const inputTokens = events.reduce((s, e) => s + e.input_tokens, 0);
  const outputTokens = events.reduce((s, e) => s + e.output_tokens, 0);
  const cacheRead = events.reduce((s, e) => s + e.cache_read_tokens, 0);
  const cacheCreation = events.reduce((s, e) => s + e.cache_creation_tokens, 0);
  const tokensSemCacheRead = inputTokens + outputTokens + cacheCreation;
  const cacheHitRate = (inputTokens + cacheRead) > 0 ? cacheRead / (inputTokens + cacheRead) : 0;
  const sessions = new Set(events.map(e => e.session_id).filter(Boolean)).size;
  const quota = quotaConsumedInRange(range);
  return { requests: events.length, sessions, totalTokens, tokensSemCacheRead, cacheHitRate, quota };
}

let compareChart = null;

// One line per group (parsed from each range's label, e.g. "A1"/"B1" ->
// groups "A"/"B"), x-axis = position within the group (1, 2, 3, ...) instead
// of creation order — makes paired comparisons (A1 vs B1, A2 vs B2, ...)
// read as parallel series instead of a misleading single timeline.
function renderCompareChart() {
  const parsed = ranges.map(r => ({ range: r, ...parseLabel(r.label), metrics: computeRangeMetrics(r) }));
  const groups = [...new Set(parsed.map(p => p.group))];
  const positions = [...new Set(parsed.map(p => p.position !== null ? p.position : p.range.label))].sort((a, b) => {
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b));
  });

  const datasets = groups.map((group, i) => {
    const byPosition = new Map(parsed.filter(p => p.group === group).map(p => [p.position !== null ? p.position : p.range.label, p]));
    return {
      label: group.trim() || "(no group)",
      data: positions.map(pos => byPosition.has(pos) ? byPosition.get(pos).metrics.totalTokens : null),
      borderColor: PALETTE[i % PALETTE.length],
      backgroundColor: PALETTE[i % PALETTE.length],
      tension: 0.25,
      pointRadius: 4,
      fill: false,
      spanGaps: false,
    };
  });

  if (compareChart) compareChart.destroy();
  compareChart = new Chart(document.getElementById("compare-chart"), {
    type: "line",
    data: { labels: positions, datasets },
    options: {
      scales: {
        x: { title: { display: true, text: "position" } },
        y: { title: { display: true, text: "total tokens" } },
      },
    },
  });
}

function renderCompare() {
  const grid = document.getElementById("compare-grid");
  grid.replaceChildren(...ranges.map((r, i) => {
    const m = computeRangeMetrics(r);

    const card = document.createElement("div");
    card.className = "metric-card";
    card.innerHTML = `
      <div class="name"><span class="swatch" style="background:${colorForLabel(r.label)}"></span>${escapeHtml(r.label)}</div>
      <dl>
        <dt>Requests</dt><dd>${m.requests.toLocaleString()}</dd>
        <dt>Sessions</dt><dd>${m.sessions.toLocaleString()}</dd>
        <dt>Total tokens</dt><dd>${m.totalTokens.toLocaleString()}</dd>
        <dt>Sem cache_read</dt><dd>${m.tokensSemCacheRead.toLocaleString()}</dd>
        <dt>Tokens/request</dt><dd>${m.requests ? Math.round(m.totalTokens / m.requests).toLocaleString() : "–"}</dd>
        <dt>Cache-hit rate</dt><dd>${(m.cacheHitRate * 100).toFixed(1)}%</dd>
        <dt>agy quota consumed</dt><dd>${(m.quota * 100).toFixed(1)}%</dd>
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
  renderCompareChart();
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


def fetch_data() -> dict:
    store = SqliteUsageStore()
    try:
        return build_dashboard_payload(store)
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=None, help="Output path (default: ~/.cache/ai-tokens-tracker/compare-report.html)")
    parser.add_argument("--no-open", action="store_true", help="Don't open the report in a browser")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else Path.home() / ".cache" / "ai-tokens-tracker" / "compare-report.html"
    out_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    payload = fetch_data()
    html = (
        TEMPLATE.replace("__EVENTS__", _json_for_script(payload["events"]))
        .replace("__SNAPSHOTS__", _json_for_script(payload["snapshots"]))
        .replace("__SESSION_TITLES__", _json_for_script(payload["session_titles"]))
    )
    out_path.write_text(html)
    out_path.chmod(0o600)

    print(f"✓ report written to {out_path}")
    if not args.no_open:
        webbrowser.open(f"file://{out_path}")


if __name__ == "__main__":
    main()
