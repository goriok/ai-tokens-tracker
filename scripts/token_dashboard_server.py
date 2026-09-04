#!/usr/bin/env python3
"""Serve a live-refreshing token usage dashboard.

Usage:
    token-dashboard-server.py [--host 127.0.0.1] [--port 8765]

Unlike token-compare-report.py (a static HTML snapshot), this keeps a small
FastAPI server running: GET / serves the comparison UI, GET /api/usage
re-reads the SQLite store on every call, so the page can poll for fresh data
without regenerating a file. Same client-side comparison model — pick ranges
in the page, nothing persisted server-side.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.sqlite_usage_store import SqliteUsageStore
from core.interfaces import UsageStore
from core.usage import build_dashboard_payload

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>token usage — live dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js"
        integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"
        crossorigin="anonymous"></script>
<style>
  :root { color-scheme: light dark; }
  html, body { height: 100%; }
  body {
    font-family: system-ui, sans-serif; margin: 0; padding: 10px 14px;
    background: Canvas; color: CanvasText; box-sizing: border-box;
    display: flex; flex-direction: column; gap: 8px; overflow: hidden;
  }
  h1 { font-size: 14px; margin: 0; display: inline; font-weight: 600; }
  h2 { font-size: 11px; margin: 0 0 6px; font-weight: 600; color: GrayText; text-transform: uppercase; letter-spacing: .02em; }
  .topbar { display: flex; align-items: baseline; gap: 10px; flex: none; }
  .sub { color: GrayText; font-size: 11px; }
  .empty { color: GrayText; font-size: 14px; padding: 40px 0; text-align: center; }
  .card { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 6px; padding: 8px 10px; min-height: 0; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent); }
  th { color: GrayText; font-weight: 500; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  button { font: inherit; font-size: 11px; padding: 2px 8px; cursor: pointer; }
  input[type=date] { font: inherit; font-size: 11px; padding: 2px 4px; }
  input[type=text] { font: inherit; font-size: 11px; padding: 2px 4px; width: 100px; }

  #content { flex: 1; min-height: 0; display: grid; grid-template-rows: minmax(0, 1.1fr) minmax(0, 1fr); gap: 8px; }
  .row-top { display: grid; grid-template-columns: 1.3fr 1fr; gap: 8px; min-height: 0; }
  .row-bottom { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; min-height: 0; }
  .card canvas { max-height: 100%; }
  .card.chart-card { display: flex; flex-direction: column; min-height: 0; }
  .card.chart-card > div { flex: 1; min-height: 0; position: relative; }

  .ranges { display: flex; flex-direction: column; gap: 4px; margin-bottom: 6px; overflow-y: auto; }
  .range-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .range-row .swatch { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .range-row .remove { margin-left: auto; color: GrayText; background: none; border: none; }

  .compare-grid { display: flex; gap: 8px; overflow-x: auto; height: 100%; }
  .metric-card { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 6px; padding: 8px 10px; flex: 1; min-width: 150px; }
  .metric-card .name { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 11px; margin-bottom: 5px; }
  .metric-card .swatch { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .metric-card dl { margin: 0; display: grid; grid-template-columns: auto auto; gap: 2px 8px; font-size: 11px; }
  .metric-card dt { color: GrayText; }
  .metric-card dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<div class="topbar">
  <h1>token usage — live dashboard</h1>
  <div class="sub" id="generated-at">loading…</div>
</div>

<div id="content"></div>

<script>
const PALETTE = ["#7aa2f7", "#9ece6a", "#e0af68", "#f7768e", "#bb9af7", "#7dcfff"];
const REFRESH_MS = 15000;

let EVENTS = [];
let SNAPSHOTS = [];
let ranges = [];
let nextId = 1;
let initialized = false;

async function fetchUsage() {
  const res = await fetch("/api/usage");
  const data = await res.json();
  EVENTS = data.events;
  SNAPSHOTS = data.snapshots;
}

async function tick() {
  await fetchUsage();
  document.getElementById("generated-at").textContent =
    `${EVENTS.length} tracked requests · ${SNAPSHOTS.length} agy quota snapshots · refreshed ${new Date().toLocaleTimeString()}`;

  if (EVENTS.length === 0 && SNAPSHOTS.length === 0) {
    document.getElementById("content").innerHTML =
      '<p class="empty">No data yet. Run claude-code-snapshot.py and/or agy-snapshot.py to start collecting.</p>';
    return;
  }
  if (!initialized) {
    ranges = defaultRanges();
    renderLayout();
    initialized = true;
  }
  renderAll();
}

function allTimestamps() {
  return [...EVENTS.map(e => e.timestamp), ...SNAPSHOTS.map(s => s.timestamp)].sort();
}

function toDateInput(ts) {
  return ts.slice(0, 10);
}

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

function renderLayout() {
  const content = document.getElementById("content");
  content.innerHTML = `
    <div class="row-top">
      <div class="card chart-card"><h2>Timeline</h2><div><canvas id="timeline-chart"></canvas></div></div>
      <div class="card" style="display:flex;flex-direction:column;">
        <h2>Ranges to compare</h2>
        <div class="ranges" id="ranges-list"></div>
        <button id="add-range">+ add range</button>
      </div>
    </div>
    <div class="row-bottom">
      <div class="card" style="overflow-y:auto;">
        <h2>Comparison</h2>
        <div class="compare-grid" id="compare-grid"></div>
      </div>
      <div class="card chart-card"><h2>Total tokens by model</h2><div><canvas id="model-chart"></canvas></div></div>
      <div class="card chart-card"><h2>Total tokens by source</h2><div><canvas id="source-chart"></canvas></div></div>
    </div>
  `;
  document.getElementById("add-range").addEventListener("click", () => {
    const ts = allTimestamps();
    const last = ts.length ? toDateInput(ts[ts.length - 1]) : new Date().toISOString().slice(0, 10);
    ranges.push({ id: nextId++, label: `range ${ranges.length + 1}`, from: last, to: last });
    renderAll();
  });
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
  const data = days.map(d => byDay.get(d).reduce((s, e) => s + e.total_tokens, 0));
  if (timelineChart) timelineChart.destroy();
  timelineChart = new Chart(document.getElementById("timeline-chart"), {
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
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } } },
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
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 10, font: { size: 10 } } } },
      scales: { x: { stacked: true }, y: { stacked: true } },
    },
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
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 10, font: { size: 10 } } } },
      scales: { x: { stacked: true }, y: { stacked: true } },
    },
  });
}

function renderAll() {
  renderTimeline();
  renderRangesList();
  renderCompare();
  renderBreakdowns();
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

tick();
setInterval(tick, REFRESH_MS);
</script>
</body>
</html>
"""


def create_app(store: UsageStore) -> FastAPI:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/usage")
    def api_usage() -> dict:
        return build_dashboard_payload(store)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    import uvicorn

    store = SqliteUsageStore()
    app = create_app(store)
    print(f"✓ dashboard at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
