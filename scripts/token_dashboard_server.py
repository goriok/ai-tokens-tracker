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
  input[type=datetime-local] { font: inherit; font-size: 11px; padding: 2px 4px; }
  input[type=text] { font: inherit; font-size: 11px; padding: 2px 4px; width: 100px; }
  select { font: inherit; font-size: 11px; padding: 2px 4px; max-width: 110px; }

  #content { flex: 1; min-height: 0; display: grid; grid-template-rows: minmax(0, 0.5fr) minmax(0, 1.6fr) minmax(0, 1fr); gap: 8px; }
  .row-top { display: grid; grid-template-columns: 1fr; min-height: 0; }
  .row-mid { display: grid; grid-template-columns: 0.8fr 1.6fr; gap: 8px; min-height: 0; }
  .row-bottom { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; min-height: 0; }
  .card canvas { max-height: 100%; }
  .card.chart-card { display: flex; flex-direction: column; min-height: 0; }
  .card.chart-card > div { flex: 1; min-height: 0; position: relative; }

  .global-window-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
  .global-window-row label { display: flex; align-items: center; gap: 4px; }
  .ranges { display: flex; flex-direction: column; gap: 8px; margin-bottom: 6px; overflow-y: auto; }
  .range-row { display: flex; flex-direction: column; gap: 3px; padding-bottom: 6px; border-bottom: 1px solid color-mix(in srgb, CanvasText 8%, transparent); }
  .range-row .row-identity, .range-row .row-period { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .range-row .swatch { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .range-row .remove { margin-left: auto; color: GrayText; background: none; border: none; }
  .range-row input[type=text] { flex: 1; min-width: 60px; }
  .range-row select { flex: 1; min-width: 90px; max-width: none; }

  .compare-card { display: flex; flex-direction: column; min-height: 0; gap: 6px; }
  .compare-chart { flex: 1; min-height: 0; position: relative; }
  .compare-grid { display: flex; gap: 6px; overflow-x: auto; flex: none; }
  .metric-card { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 6px; padding: 6px 8px; flex: 1; min-width: 140px; }
  .metric-card .name { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 11px; margin-bottom: 4px; }
  .metric-card .swatch { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .metric-card dl { margin: 0; display: grid; grid-template-columns: auto auto; gap: 1px 8px; font-size: 10px; }
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
let SESSION_TITLES = [];
let ranges = [];
let nextId = 1;
let initialized = false;
let globalWindow = { enabled: true, from: "", to: "" };

async function fetchUsage() {
  const res = await fetch("/api/usage");
  const data = await res.json();
  EVENTS = data.events;
  SNAPSHOTS = data.snapshots;
  SESSION_TITLES = data.session_titles || [];
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
    if (globalWindow.enabled && !globalWindow.from && !globalWindow.to) {
      const { from, to } = defaultWindow();
      globalWindow.from = from;
      globalWindow.to = to;
    }
    ranges = defaultRanges();
    renderLayout();
    initialized = true;
  }
  renderAll();
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

function renderLayout() {
  const content = document.getElementById("content");
  content.innerHTML = `
    <div class="row-top">
      <div class="card chart-card"><h2>Timeline</h2><div><canvas id="timeline-chart"></canvas></div></div>
    </div>
    <div class="row-mid">
      <div class="card" style="display:flex;flex-direction:column;">
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
      <div class="card compare-card">
        <h2>Comparison</h2>
        <div class="compare-chart"><canvas id="compare-chart"></canvas></div>
        <div class="compare-grid" id="compare-grid"></div>
      </div>
    </div>
    <div class="row-bottom">
      <div class="card chart-card"><h2>Total tokens by model</h2><div><canvas id="model-chart"></canvas></div></div>
      <div class="card chart-card"><h2>Total tokens by source</h2><div><canvas id="source-chart"></canvas></div></div>
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
  gwToggle.addEventListener("change", () => {
    globalWindow.enabled = gwToggle.checked;
    if (globalWindow.enabled && !globalWindow.from && !globalWindow.to) {
      const { from, to } = defaultWindow();
      globalWindow.from = from;
      globalWindow.to = to;
    }
    renderLayout();
    renderAll();
  });
  gwFrom.addEventListener("change", () => { globalWindow.from = gwFrom.value; renderAll(); });
  gwTo.addEventListener("change", () => { globalWindow.to = gwTo.value; renderAll(); });
  [gwFrom, gwArrow, gwTo].forEach(el => { el.hidden = !globalWindow.enabled; });
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
      maintainAspectRatio: false,
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
              renderLayout();
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
      maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 10, font: { size: 10 } } } },
      scales: {
        x: { title: { display: true, text: "position", font: { size: 9 } } },
        y: { title: { display: true, text: "total tokens", font: { size: 9 } }, ticks: { font: { size: 9 } } },
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
  renderCompareChart();
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
