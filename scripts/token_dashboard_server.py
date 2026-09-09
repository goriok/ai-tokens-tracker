#!/usr/bin/env python3
"""Serve a live-refreshing token usage dashboard.

Usage:
    token-dashboard-server.py [--host 127.0.0.1] [--port 8765]

Keeps a small FastAPI server running: GET / serves the comparison UI, GET
/api/usage re-reads the SQLite store on every call, so the page can poll for
fresh data without regenerating a file. Client-side comparison model — pick
sessions in the page (or pre-load them via URL params), nothing persisted
server-side.
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
    font-family: system-ui, sans-serif; font-size: 14px; margin: 0; padding: 10px 14px;
    background: Canvas; color: CanvasText; box-sizing: border-box;
    display: flex; flex-direction: column; gap: 8px; overflow: hidden;
  }
  h1 { font-size: 18px; margin: 0; display: inline; font-weight: 600; }
  h2 { font-size: 14px; margin: 0 0 6px; font-weight: 600; color: GrayText; text-transform: uppercase; letter-spacing: .02em; }
  .topbar { display: flex; align-items: center; gap: 10px; flex: none; flex-wrap: wrap; }
  .topbar h1 { flex: none; }
  .topbar .global-window-row { margin: 0; padding: 0; border: none; gap: 6px; }
  .topbar .sub { margin-left: auto; }
  .sub { color: GrayText; font-size: 14px; }
  .empty { color: GrayText; font-size: 16px; padding: 40px 0; text-align: center; }
  .card { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 6px; padding: 8px 10px; min-height: 0; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent); }
  th { color: GrayText; font-weight: 500; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  button { font: inherit; font-size: 14px; padding: 3px 10px; cursor: pointer; }
  input[type=datetime-local] { font: inherit; font-size: 14px; padding: 3px 6px; }
  input[type=text] { font: inherit; font-size: 14px; padding: 3px 6px; width: 100px; }
  select { font: inherit; font-size: 14px; padding: 3px 6px; max-width: 140px; }

  #content { flex: 1; min-height: 0; display: grid; grid-template-rows: minmax(0, 0.45fr) minmax(0, 2fr) minmax(0, 0.8fr); gap: 8px; }
  .row-top { display: grid; grid-template-columns: 1fr; min-height: 0; }
  .row-mid { display: grid; grid-template-columns: 0.55fr 1.85fr; gap: 8px; min-height: 0; }
  .row-mid.sessions-collapsed { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
  .row-mid.sessions-collapsed #sessions-card { grid-column: 1; grid-row: 1; }
  .row-mid.sessions-collapsed .compare-card { grid-column: 1; grid-row: 2; }
  .row-bottom { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; min-height: 0; }
  .card canvas { max-height: 100%; }
  .card.chart-card { display: flex; flex-direction: column; min-height: 0; }
  .card.chart-card > div { flex: 1; min-height: 0; position: relative; }

  #sessions-card[open] { display: flex; flex-direction: column; overflow: hidden; }
  #sessions-card:not([open]) { min-height: 0; }
  #sessions-card summary { cursor: pointer; list-style: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #sessions-card summary::-webkit-details-marker { display: none; }
  #sessions-card summary h2 { display: inline; white-space: nowrap; }
  #sessions-card:not([open]) summary { margin: 0; }
  .global-window-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
  .global-window-row label { display: flex; align-items: center; gap: 4px; }
  #preset-range-list { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
  .preset-range { background: none; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: 4px; padding: 3px 8px; font-size: 12px; color: CanvasText; }
  .preset-range:hover { background: color-mix(in srgb, CanvasText 6%, transparent); }
  .preset-range.active { background: color-mix(in srgb, CanvasText 12%, transparent); border-color: color-mix(in srgb, CanvasText 40%, transparent); font-weight: 600; }
  .custom-range-toggle { background: none; border: none; color: GrayText; font-size: 12px; padding: 3px 4px; }
  .custom-range-toggle:hover { color: CanvasText; }
  .custom-range-inputs { display: none; align-items: center; gap: 6px; }
  .custom-range-inputs.open { display: flex; }
  .sessions { display: flex; flex-direction: column; gap: 8px; margin-bottom: 6px; overflow-y: auto; flex: none; max-height: 40%; }
  .add-session-row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .add-session-row input[type=text] { flex: 1; }
  .session-row { display: flex; flex-direction: column; gap: 3px; padding-bottom: 6px; border-bottom: 1px solid color-mix(in srgb, CanvasText 8%, transparent); }
  .session-row .row-identity { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .session-row .swatch { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .session-row .remove { margin-left: auto; color: GrayText; background: none; border: none; }
  .session-row .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .suggestions-heading { font-size: 11px; color: GrayText; text-transform: uppercase; letter-spacing: .02em; margin: 4px 0; }
  .suggestions { display: flex; flex-direction: column; gap: 2px; overflow-y: auto; min-height: 0; flex: 1; }
  .suggestion-row { display: flex; align-items: center; gap: 6px; background: none; border: none; text-align: left; padding: 3px 4px; border-radius: 4px; width: 100%; }
  .suggestion-row:hover:not(:disabled) { background: color-mix(in srgb, CanvasText 6%, transparent); }
  .suggestion-row:disabled { opacity: 0.4; cursor: default; }
  .suggestion-row .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .suggestion-row .tokens { color: GrayText; font-variant-numeric: tabular-nums; font-size: 12px; flex: none; }

  .compare-card { display: flex; flex-direction: column; min-height: 0; gap: 6px; }
  .compare-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .compare-header h2 { margin: 0; }
  .compare-header label { display: flex; align-items: center; gap: 4px; font-size: 13px; color: GrayText; }
  .compare-chart { flex: 1; min-height: 0; position: relative; }
  .compare-grid { display: flex; gap: 6px; overflow-x: auto; flex: none; }
  .metric-card { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 6px; padding: 7px 9px; flex: 1; min-width: 170px; }
  .metric-card .name { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 14px; margin-bottom: 4px; }
  .metric-card .swatch { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .metric-card dl { margin: 0; display: grid; grid-template-columns: auto auto; gap: 2px 8px; font-size: 12px; }
  .metric-card dt { color: GrayText; }
  .metric-card dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<div class="topbar">
  <h1>token usage — live dashboard</h1>
  <div class="global-window-row">
    <label>window:</label>
    <div id="preset-range-list"></div>
    <button class="custom-range-toggle" id="custom-range-toggle" type="button" title="custom range">custom…</button>
    <div class="custom-range-inputs" id="custom-range-inputs">
      <input type="datetime-local" step="1" id="global-window-from">
      <span id="global-window-arrow">→</span>
      <input type="datetime-local" step="1" id="global-window-to">
    </div>
  </div>
  <label>tool: <select id="filter-tool"><option value="">any</option></select></label>
  <div class="sub" id="generated-at">loading…</div>
</div>

<div id="content"></div>

<script>
const PALETTE = ["#7aa2f7", "#9ece6a", "#e0af68", "#f7768e", "#bb9af7", "#7dcfff"];
const REFRESH_MS = 30000;

let EVENTS = [];
let SNAPSHOTS = [];
let SESSION_TITLES = [];
let sessions = [];
let nextId = 1;
let initialized = false;
// The one and only time filter — sessions no longer carry their own from/to,
// they're just named subsets (by label) clipped to this window (see
// eventsForSession).
let globalWindow = { from: "", to: "" };

// Global filter (topbar): restricts every chart/breakdown/comparison to one
// tool/source, not just the "add session" matcher. Empty string means "any".
// Populated dynamically from the values actually present in namedRuns(),
// never hardcoded, same principle as the model/source breakdown charts.
let toolFilter = "";

// Global switch (not per-source): whether cache-creation/write tokens count
// toward totals and charts at all. Off by default — agy doesn't report this
// dimension, so including it by default would silently make agy read as
// cheaper than sources that do report it (Claude Code, Copilot) any time a
// comparison mixes sources. Toggle it on deliberately when comparing only
// sources that all report it, or when the gap itself is what you want to see.
let includeCacheCreation = false;

// Single choke point for "total tokens" everywhere in the UI (timeline,
// model/source breakdowns, compare cards) so the includeCacheCreation
// toggle affects the whole dashboard uniformly, not just one chart.
function eventTotalTokens(e) {
  return e.input_tokens + e.output_tokens + e.cache_read_tokens + (includeCacheCreation ? e.cache_creation_tokens : 0);
}

// Server-side time window for /api/usage, read once from the URL at module
// load (from=/to=, or since=/until= as an explicit alias for the same
// thing). Full history is tens of thousands of events (~8MB JSON as of this
// writing) — most of it irrelevant to any one comparison, and downloading
// it every fetchUsage() call is what actually made the page heavy. Filter
// server-side by passing this to /api/usage, not just in the browser after
// download. Leave both empty (no params) to fall back to the full history,
// same as before this existed.
// If prefix= looks like the YYYYMMDDHHmm round-prefix these experiment
// scripts stamp into every label (they can't use Date.now() themselves —
// see Workflow tool docs — so the caller always passes a real timestamp),
// derive a since= bound from it automatically: an event can't have a
// timestamp earlier than the round that generated its label. Cheap,
// correct lower bound — no need to also type since= by hand for the common
// case of "just show me this round's data."
function sinceFromPrefix(prefix) {
  const m = /^(\\d{4})(\\d{2})(\\d{2})(\\d{2})(\\d{2})/.exec(prefix || "")
  if (!m) return null
  const [, yyyy, mo, dd, hh, mi] = m
  return `${yyyy}-${mo}-${dd}T${hh}:${mi}:00`
}

const FETCH_WINDOW = (() => {
  const params = new URLSearchParams(window.location.search)
  return {
    since: params.get("since") || params.get("from") || sinceFromPrefix(params.get("prefix")),
    until: params.get("until") || params.get("to") || null,
  }
})()

async function fetchUsage() {
  const qs = new URLSearchParams()
  if (FETCH_WINDOW.since) qs.set("since", FETCH_WINDOW.since)
  if (FETCH_WINDOW.until) qs.set("until", FETCH_WINDOW.until)
  const res = await fetch(`/api/usage${qs.toString() ? `?${qs}` : ""}`);
  const data = await res.json();
  EVENTS = data.events;
  SNAPSHOTS = data.snapshots;
  SESSION_TITLES = data.session_titles || [];
}

// URL params let a dashboard link pre-load a specific comparison instead of
// starting from the empty picker — e.g. share a link straight to one
// experiment round's sessions. Supported params:
//   prefix=<text>   add one session per known session/run whose title starts
//                    with <text> (matched against the bare title, not
//                    displayTitle, so it doesn't need the "(source, date)"
//                    suffix) — the common case, one param covers N runs.
//   sessions=a,b,c  add one session per exact displayTitle, comma-separated
//                    (URL-encode commas/parens inside a title if needed).
//   tool=<source>   pre-selects the global tool filter.
//   from=, to=      datetime-local values (YYYY-MM-DDTHH:MM:SS) for the
//                    global window — only applied when provided. ALSO used
//                    as the server-side fetch window (see FETCH_WINDOW)
//                    unless since=/until= are given instead.
//   since=, until=  explicit alias for the server-side fetch window when
//                    you want to fetch a wider/narrower range than the
//                    global window itself (e.g. fetch a whole day but only
//                    highlight one hour as the global window).
function sessionsFromUrlParams() {
  const params = new URLSearchParams(window.location.search);
  const runs = namedRuns();
  const out = [];
  const seen = new Set();

  const prefix = params.get("prefix");
  if (prefix) {
    runs.filter(r => r.title.startsWith(prefix)).forEach(r => {
      if (seen.has(r.displayTitle)) return;
      seen.add(r.displayTitle);
      out.push(r);
    });
  }

  const explicit = params.get("sessions");
  if (explicit) {
    explicit.split(",").map(s => s.trim()).filter(Boolean).forEach(title => {
      const run = runs.find(r => r.displayTitle === title || r.title === title);
      if (!run || seen.has(run.displayTitle)) return;
      seen.add(run.displayTitle);
      out.push(run);
    });
  }

  return out.map(run => ({ id: nextId++, label: run.displayTitle }));
}

function applyGlobalWindowFromUrlParams() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("from")) { globalWindow.from = params.get("from"); activePresetId = null; }
  if (params.has("to")) { globalWindow.to = params.get("to"); activePresetId = null; }
}

function applyToolFilterFromUrlParams() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("tool")) toolFilter = params.get("tool");
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
    if (!globalWindow.from && !globalWindow.to) {
      const { from, to } = defaultWindow();
      globalWindow.from = from;
      globalWindow.to = to;
    }
    applyGlobalWindowFromUrlParams();
    applyToolFilterFromUrlParams();
    sessions = defaultSessions();
    const urlSessions = sessionsFromUrlParams();
    if (urlSessions.length > 0) sessions = urlSessions;
    initGlobalWindowControls();
    renderLayout();
    initialized = true;
  }
  renderAll();
}

function toDateTimeInput(ts) {
  // UTC, no timezone conversion — what you type is what's compared.
  return ts.slice(0, 19);
}

function toDateInput(ts) {
  return ts.slice(0, 10);
}

// Quick-pick windows, sliding relative to "now" at click time — not fixed
// calendar days. Order here is display order (shortest first).
const PRESET_RANGES = [
  { id: "5m", label: "5m", ms: 5 * 60 * 1000 },
  { id: "30m", label: "30m", ms: 30 * 60 * 1000 },
  { id: "1h", label: "1h", ms: 60 * 60 * 1000 },
  { id: "3h", label: "3h", ms: 3 * 60 * 60 * 1000 },
  { id: "6h", label: "6h", ms: 6 * 60 * 60 * 1000 },
  { id: "12h", label: "12h", ms: 12 * 60 * 60 * 1000 },
  { id: "1d", label: "1d", ms: 24 * 60 * 60 * 1000 },
  { id: "2d", label: "2d", ms: 2 * 24 * 60 * 60 * 1000 },
  { id: "7d", label: "7d", ms: 7 * 24 * 60 * 60 * 1000 },
  { id: "14d", label: "14d", ms: 14 * 24 * 60 * 60 * 1000 },
  { id: "30d", label: "30d", ms: 30 * 24 * 60 * 60 * 1000 },
];
const DEFAULT_PRESET_ID = "30m";

let activePresetId = null;

function defaultWindow() {
  const preset = PRESET_RANGES.find(p => p.id === DEFAULT_PRESET_ID);
  activePresetId = preset.id;
  return windowForPreset(preset);
}

function windowForPreset(preset) {
  const now = new Date();
  const from = new Date(now.getTime() - preset.ms);
  return {
    from: toDateTimeInput(from.toISOString()),
    to: toDateTimeInput(now.toISOString()),
  };
}

// No sessions by default — an empty list shows the picker with nothing
// selected, so nothing is compared until you say so.
function defaultSessions() {
  return [];
}

// A link that already carries sessions (?prefix=/?sessions=) is someone
// opening a pre-built comparison to read the result, not to assemble one —
// so the picker starts collapsed for them. Anyone building a comparison by
// hand (no sessions in the URL) starts with it open, as before.
function hasSessionsInUrl() {
  const params = new URLSearchParams(window.location.search);
  return Boolean(params.get("prefix") || params.get("sessions"));
}

function renderLayout() {
  const content = document.getElementById("content");
  const sessionsOpen = !hasSessionsInUrl();
  content.innerHTML = `
    <div class="row-top">
      <div class="card chart-card"><h2>Timeline</h2><div><canvas id="timeline-chart"></canvas></div></div>
    </div>
    <div class="row-mid ${sessionsOpen ? "" : "sessions-collapsed"}" id="row-mid">
      <details class="card" id="sessions-card" ${sessionsOpen ? "open" : ""}>
        <summary><h2 style="display:inline">Sessions to compare</h2></summary>
        <div class="add-session-row">
          <input type="text" id="add-session-input" placeholder="session name or prefix">
          <button id="add-session" title="add session">+</button>
        </div>
        <div class="sessions" id="sessions-list"></div>
        <div class="suggestions-heading">Sessions in window (click to add)</div>
        <div class="suggestions" id="suggestions-list"></div>
      </details>
      <div class="card compare-card">
        <div class="compare-header">
          <h2>Comparison</h2>
          <label>breakdown: <select id="breakdown-mode-select">
            <option value="cache" selected>cache hit vs. miss</option>
            <option value="io">input/output/cache</option>
          </select></label>
          <label title="agy doesn't report cache-creation/write tokens — including this dimension makes agy look cheaper than sources that do report it, unless you're comparing sources that all measure it.">
            <input type="checkbox" id="cache-creation-toggle"> include cache creation
          </label>
        </div>
        <div class="compare-chart"><canvas id="compare-chart"></canvas></div>
        <div class="compare-grid" id="compare-grid"></div>
      </div>
    </div>
    <div class="row-bottom">
      <div class="card chart-card"><h2>Total tokens by model</h2><div><canvas id="model-chart"></canvas></div></div>
      <div class="card chart-card"><h2>Total tokens by source</h2><div><canvas id="source-chart"></canvas></div></div>
    </div>
  `;
  const sessionsCard = document.getElementById("sessions-card");
  const rowMid = document.getElementById("row-mid");
  sessionsCard.addEventListener("toggle", () => {
    rowMid.classList.toggle("sessions-collapsed", !sessionsCard.open);
  });

  const addSessionInput = document.getElementById("add-session-input");
  const addSession = () => {
    const query = addSessionInput.value.trim();
    if (!query) return;
    addSessionsByNameOrPrefix(query);
    addSessionInput.value = "";
    renderAll();
  };
  document.getElementById("add-session").addEventListener("click", addSession);
  addSessionInput.addEventListener("keydown", e => { if (e.key === "Enter") addSession(); });

  const breakdownSelect = document.getElementById("breakdown-mode-select");
  breakdownSelect.value = breakdownMode;
  breakdownSelect.addEventListener("change", () => {
    breakdownMode = breakdownSelect.value;
    renderCompareChart();
  });

  const cacheCreationToggle = document.getElementById("cache-creation-toggle");
  cacheCreationToggle.checked = includeCacheCreation;
  cacheCreationToggle.addEventListener("change", () => {
    includeCacheCreation = cacheCreationToggle.checked;
    renderTimeline();
    renderCompareChart();
    renderCompare();
    renderBreakdowns();
  });

  document.getElementById("filter-tool").addEventListener("change", e => {
    toolFilter = e.target.value;
    renderAll();
  });

  syncGlobalWindowControls();
}

// Adds one session per known run whose displayTitle matches exactly, or
// whose bare title starts with `query` — same matching rule as the
// ?prefix=/?sessions= URL params (see sessionsFromUrlParams), just typed
// directly into the picker instead of the URL.
function addSessionsByNameOrPrefix(query) {
  const runs = namedRuns();
  const used = new Set(sessions.map(r => r.label));
  const exact = runs.find(r => r.displayTitle === query || r.title === query);
  const matches = exact ? [exact] : runs.filter(r => r.title.startsWith(query));
  matches.forEach(run => {
    if (used.has(run.displayTitle)) return;
    used.add(run.displayTitle);
    sessions.push({ id: nextId++, label: run.displayTitle });
  });
}

// Global-window controls live in the static topbar (outside #content), so
// they're wired once — not re-attached on every renderLayout() — and this
// just syncs their displayed value to the current state.
function syncGlobalWindowControls() {
  document.getElementById("global-window-from").value = globalWindow.from;
  document.getElementById("global-window-to").value = globalWindow.to;
  document.querySelectorAll(".preset-range").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.presetId === activePresetId);
  });
}

function applyPresetRange(preset) {
  activePresetId = preset.id;
  const { from, to } = windowForPreset(preset);
  globalWindow.from = from;
  globalWindow.to = to;
  document.getElementById("custom-range-inputs").classList.remove("open");
  syncGlobalWindowControls();
  tick();
}

function renderPresetRangeList() {
  const list = document.getElementById("preset-range-list");
  list.innerHTML = PRESET_RANGES.map(p =>
    `<button type="button" class="preset-range" data-preset-id="${p.id}">${p.label}</button>`
  ).join("");
  list.querySelectorAll(".preset-range").forEach((btn, i) => {
    btn.addEventListener("click", () => applyPresetRange(PRESET_RANGES[i]));
  });
}

function initGlobalWindowControls() {
  renderPresetRangeList();

  const gwFrom = document.getElementById("global-window-from");
  const gwTo = document.getElementById("global-window-to");
  const onCustomChange = () => {
    activePresetId = null;
    globalWindow.from = gwFrom.value;
    globalWindow.to = gwTo.value;
    syncGlobalWindowControls();
    tick();
  };
  gwFrom.addEventListener("change", onCustomChange);
  gwTo.addEventListener("change", onCustomChange);

  document.getElementById("custom-range-toggle").addEventListener("click", () => {
    document.getElementById("custom-range-inputs").classList.toggle("open");
  });
}

// Each session is colored individually by creation order (see PALETTE[i % ...]
// at each call site).

// Single choke point for the global tool filter — everything that reads
// EVENTS directly (timeline fallback, namedRuns, model/source breakdowns)
// goes through this instead, so picking a tool in the topbar scopes the
// whole dashboard, not just the session picker.
function filteredEvents() {
  return toolFilter ? EVENTS.filter(e => e.source === toolFilter) : EVENTS;
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

// With no sessions selected, the timeline shows the full history (nothing to
// scope to yet). Once sessions are active, it scopes to exactly what's in
// the comparison below — so it never implies activity from runs that were
// filtered out of the comparison.
function eventDedupeKey(e) {
  return `${e.timestamp}|${e.session_id}|${e.label}|${e.total_tokens}`;
}

function timelineEvents() {
  if (sessions.length === 0) return filteredEvents().filter(e => inGlobalWindow(e.timestamp));
  const seen = new Set();
  const out = [];
  for (const s of sessions) {
    for (const e of eventsForSession(s)) {
      const key = eventDedupeKey(e);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(e);
    }
  }
  return out;
}

// Bucket width for the timeline's x-axis, driven by the span actually shown
// (the global window, or the shown events' own min..max before it's set) —
// a one-day window buried in hourly buckets is unreadable as a handful of
// daily dots, and a year of data grouped by hour would be thousands of
// unreadable points. Thresholds are on calendar span, not point count.
const TIMELINE_GRANULARITIES = [
  { maxSpanMs: 3 * 24 * 60 * 60 * 1000, unit: "hour", bucket: ts => ts.slice(0, 13) + ":00:00" },
  { maxSpanMs: 60 * 24 * 60 * 60 * 1000, unit: "day", bucket: ts => toDateInput(ts) + "T12:00:00" },
  { maxSpanMs: Infinity, unit: "week", bucket: ts => {
      const d = new Date(toDateInput(ts) + "T00:00:00Z");
      d.setUTCDate(d.getUTCDate() - d.getUTCDay());
      return d.toISOString().slice(0, 10) + "T12:00:00";
    } },
];

function timelineGranularity(events) {
  let fromMs, toMs;
  if (globalWindow.from && globalWindow.to) {
    fromMs = new Date(globalWindow.from + "Z").getTime();
    toMs = new Date(globalWindow.to + "Z").getTime();
  } else {
    const ts = events.map(e => e.timestamp).sort();
    if (ts.length === 0) return TIMELINE_GRANULARITIES[1];
    fromMs = new Date(ts[0]).getTime();
    toMs = new Date(ts[ts.length - 1]).getTime();
  }
  const spanMs = Math.max(0, toMs - fromMs);
  return TIMELINE_GRANULARITIES.find(g => spanMs <= g.maxSpanMs);
}

function renderTimeline() {
  const events = timelineEvents();
  const granularity = timelineGranularity(events);
  const sources = [...new Set(events.map(e => e.source))].sort();
  const datasets = sources.map((src, i) => {
    const byBucket = groupBy(events.filter(e => e.source === src), e => granularity.bucket(e.timestamp));
    const buckets = [...byBucket.keys()].sort();
    const points = buckets.map(b => ({ x: b + "Z", y: byBucket.get(b).reduce((s, e) => s + eventTotalTokens(e), 0) }));
    const color = PALETTE[i % PALETTE.length];
    return {
      label: src,
      data: points,
      borderColor: color,
      backgroundColor: color,
      tension: 0.25,
      pointRadius: 3,
      fill: false,
    };
  });
  if (timelineChart) timelineChart.destroy();
  timelineChart = new Chart(document.getElementById("timeline-chart"), {
    type: "line",
    data: { datasets },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: datasets.length > 1, labels: { boxWidth: 12, font: { size: 12 } } },
        zoom: {
          zoom: {
            drag: { enabled: true },
            mode: "x",
            onZoomComplete: ({ chart }) => {
              const { min, max } = chart.scales.x;
              globalWindow.from = toDateTimeInput(new Date(min).toISOString());
              globalWindow.to = toDateTimeInput(new Date(max).toISOString());
              activePresetId = null;
              chart.resetZoom();
              renderLayout();
              renderAll();
              syncGlobalWindowControls();
            },
          },
        },
      },
      scales: { x: { type: "time", time: { unit: granularity.unit } } },
    },
  });
}

function inGlobalWindow(ts) {
  const t = toDateTimeInput(ts);
  return (!globalWindow.from || t >= globalWindow.from) && (!globalWindow.to || t <= globalWindow.to);
}

// A session is just a label, always clipped to the global window (see
// globalWindow) — it never carries its own from/to. If the label matches one
// specific session/agy run (exact title), scope to that run's events; an
// unmatched free-text label falls back to "everything in the window" (e.g. a
// "baseline: all" session next to specific-run sessions).
function eventsForSession(session) {
  const run = namedRuns().find(r => r.displayTitle === session.label);
  const pool = run ? run.events : filteredEvents();
  return pool.filter(e => inGlobalWindow(e.timestamp));
}

// Unifies three ways a run can be named: any source's session_id (grouped
// by session_id — Claude Code and Copilot both stamp every event with one),
// a Claude Code session's custom title (looked up from SESSION_TITLES to
// label that session_id-based group instead of showing the raw id), and any
// other source's TaskCall --task label for events with no session_id at all
// (1 event = 1 label — covers agy, and any future label-based source
// without more hardcoding). Each becomes a { key, title, source, events }
// entry so the session picker doesn't need to know which kind it's choosing
// between. Titles are always shown raw — no attempt to decode a naming
// convention out of them.
//
// displayTitle always includes source + start date ("A1 (claude-code,
// 2026-09-04)") — two runs can share a bare title (different sources, or a
// typo like naming two sessions "A1"), and matching by title alone would
// silently pick whichever came first. Matching is always done against
// displayTitle, never the bare title.
function namedRuns() {
  const events = filteredEvents();
  const sessionTitleById = new Map(SESSION_TITLES.map(t => [t.session_id, t.title]));
  const sessionIds = [...new Set(events.filter(e => e.session_id).map(e => e.session_id))];
  const bySession = sessionIds.map(session_id => {
    const sessionEvents = events.filter(e => e.session_id === session_id);
    return {
      key: `session:${session_id}`,
      title: sessionTitleById.get(session_id) || session_id,
      source: sessionEvents[0].source,
      events: sessionEvents,
    };
  });
  const labeledSources = [...new Set(events.filter(e => !e.session_id && e.label).map(e => e.source))];
  const byLabel = labeledSources.flatMap(source => {
    const labels = [...new Set(events.filter(e => e.source === source && !e.session_id && e.label).map(e => e.label))];
    return labels.map(label => ({
      key: `label:${source}:${label}`,
      title: label,
      source,
      events: events.filter(e => e.source === source && !e.session_id && e.label === label),
    }));
  });
  return [...bySession, ...byLabel]
    .filter(r => r.events.length > 0)
    .map(r => {
      const ts = r.events.map(e => e.timestamp).sort();
      const day = ts.length > 0 ? toDateInput(ts[0]) : "?";
      return { ...r, displayTitle: `${r.title} (${r.source}, ${day})` };
    })
    .sort((a, b) => a.displayTitle.localeCompare(b.displayTitle));
}

// Fills a <select> with one <option> per distinct value found in `values`
// (sorted), preserving "any" as the first option and the current selection
// if it's still a valid choice — same populate-from-data pattern already
// used for the model/source breakdown charts, applied to the global tool
// filter.
function populateFilterSelect(select, values, current) {
  const distinct = [...new Set(values)].filter(Boolean).sort();
  select.replaceChildren(
    ...[{ value: "", label: "any" }, ...distinct.map(v => ({ value: v, label: v }))].map(({ value, label }) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      return opt;
    })
  );
  select.value = distinct.includes(current) ? current : "";
}

function renderSessionsList() {
  const list = document.getElementById("sessions-list");

  populateFilterSelect(document.getElementById("filter-tool"), EVENTS.map(e => e.source), toolFilter);

  const children = sessions.map((s, i) => {
    const row = document.createElement("div");
    row.className = "session-row";

    const identity = document.createElement("div");
    identity.className = "row-identity";

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = PALETTE[i % PALETTE.length];
    identity.appendChild(swatch);

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = s.label;
    identity.appendChild(title);

    const remove = document.createElement("button");
    remove.className = "remove";
    remove.textContent = "remove";
    remove.addEventListener("click", () => { sessions.splice(i, 1); renderAll(); });
    identity.appendChild(remove);

    row.appendChild(identity);

    return row;
  });

  if (children.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.style.padding = "12px 0";
    empty.textContent = "No sessions added yet.";
    children.push(empty);
  }

  list.replaceChildren(...children);
  renderSuggestionsList();
}

// Every known run (already scoped to the tool filter by namedRuns) that has
// at least one event inside the global window, ranked by tokens actually
// within that window — so picking a narrower window re-ranks the list
// instead of just hiding/showing a fixed top-N. Click adds it to the
// comparison directly, same as typing its exact title in add-session-input.
function renderSuggestionsList() {
  const list = document.getElementById("suggestions-list");
  const used = new Set(sessions.map(s => s.label));

  const ranked = namedRuns()
    .map(run => ({ run, tokens: run.events.filter(e => inGlobalWindow(e.timestamp)).reduce((s, e) => s + eventTotalTokens(e), 0) }))
    .filter(r => r.tokens > 0)
    .sort((a, b) => b.tokens - a.tokens);

  const children = ranked.map(({ run, tokens }) => {
    const alreadyAdded = used.has(run.displayTitle);
    const row = document.createElement("button");
    row.type = "button";
    row.className = "suggestion-row";
    row.disabled = alreadyAdded;
    row.title = alreadyAdded ? "already added" : run.displayTitle;

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = run.displayTitle;
    row.appendChild(title);

    const tokensEl = document.createElement("span");
    tokensEl.className = "tokens";
    tokensEl.textContent = tokens.toLocaleString();
    row.appendChild(tokensEl);

    row.addEventListener("click", () => {
      sessions.push({ id: nextId++, label: run.displayTitle });
      renderAll();
    });

    return row;
  });

  if (children.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.style.padding = "8px 0";
    empty.textContent = "No sessions in this window.";
    children.push(empty);
  }

  list.replaceChildren(...children);
}

function quotaConsumedForSession(session) {
  const matches = s => inGlobalWindow(s.timestamp);
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

function computeSessionMetrics(session) {
  const events = eventsForSession(session);
  const inputTokens = events.reduce((s, e) => s + e.input_tokens, 0);
  const outputTokens = events.reduce((s, e) => s + e.output_tokens, 0);
  const cacheRead = events.reduce((s, e) => s + e.cache_read_tokens, 0);
  const cacheCreation = events.reduce((s, e) => s + e.cache_creation_tokens, 0);
  // false if ANY event in this session comes from a source that doesn't
  // report cache-write at all (agy, as of this writing) — cacheCreation
  // would then read as "confirmed 0" when it's really "unmeasured." Shown
  // as a caveat regardless of includeCacheCreation, since it explains why a
  // session's number may understate its real cost.
  const cacheCreationFullyMeasured = events.length > 0 && events.every(e => e.cache_creation_measured);
  const totalTokens = events.reduce((s, e) => s + eventTotalTokens(e), 0);
  const tokensSemCacheRead = inputTokens + outputTokens + (includeCacheCreation ? cacheCreation : 0);
  const cacheHitRate = (inputTokens + cacheRead) > 0 ? cacheRead / (inputTokens + cacheRead) : 0;
  const sessions = new Set(events.map(e => e.session_id).filter(Boolean)).size;
  const quota = quotaConsumedForSession(session);
  const scored = events.filter(e => e.confidence_score != null);
  const confidenceScore = scored.length > 0 ? scored.reduce((s, e) => s + e.confidence_score, 0) / scored.length : null;
  return { requests: events.length, sessions, totalTokens, tokensSemCacheRead, inputTokens, outputTokens, cacheRead, cacheCreation, cacheCreationFullyMeasured, cacheHitRate, quota, confidenceScore, confidenceScoredCount: scored.length };
}

let compareChart = null;
let breakdownMode = "cache";

function earliestTimestamp(session) {
  const ts = eventsForSession(session).map(e => e.timestamp).sort();
  return ts.length > 0 ? ts[0] : null;
}

// A lighter tint of a session's base color, for the "less interesting" part
// of a stacked segment (e.g. cache_read — already-paid-for reuse) so the
// darker full-color segment draws the eye to what actually cost something new.
function lighten(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 0xff, g = (n >> 8) & 0xff, b = n & 0xff;
  const mix = c => Math.round(c + (255 - c) * amount);
  return `rgb(${mix(r)}, ${mix(g)}, ${mix(b)})`;
}

// Horizontal bars, one per session, ordered by real start time — total tokens
// is a magnitude per session, not a continuous series, so bars compare
// magnitude directly without a line implying a trend that isn't there.
// Stacked into segments (cache hit vs. miss, or input/output/cache) so each
// session's own color still identifies it, tinted lighter for cache reuse.
function renderCompareChart() {
  const points = sessions
    .map((s, i) => ({ session: s, i, metrics: computeSessionMetrics(s), t: earliestTimestamp(s) }))
    .filter(p => p.t !== null)
    .sort((a, b) => a.t.localeCompare(b.t));

  const labels = points.map(p => p.session.label);
  const colors = points.map(p => PALETTE[p.i % PALETTE.length]);

  const datasets = breakdownMode === "cache"
    ? [
        { label: "Cache miss", data: points.map(p => p.metrics.tokensSemCacheRead), backgroundColor: colors },
        { label: "Cache hit", data: points.map(p => p.metrics.cacheRead), backgroundColor: colors.map(c => lighten(c, 0.55)) },
      ]
    : [
        { label: "Input", data: points.map(p => p.metrics.inputTokens), backgroundColor: colors },
        { label: "Output", data: points.map(p => p.metrics.outputTokens), backgroundColor: colors.map(c => lighten(c, 0.25)) },
        { label: "Cache creation", data: points.map(p => p.metrics.cacheCreation), backgroundColor: colors.map(c => lighten(c, 0.45)) },
        { label: "Cache hit", data: points.map(p => p.metrics.cacheRead), backgroundColor: colors.map(c => lighten(c, 0.65)) },
      ];

  // Fewer bars means more vertical room per label, so the y-axis text can
  // afford to be bigger — 12 individual sessions need to stay compact to
  // fit without overlapping, while 4 grouped bars have room to read easily.
  const yAxisFontSize = Math.max(12, Math.min(20, Math.round(140 / Math.max(labels.length, 1))));

  if (compareChart) compareChart.destroy();
  compareChart = new Chart(document.getElementById("compare-chart"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 12, font: { size: 12 } } } },
      scales: {
        x: { stacked: true, title: { display: true, text: "total tokens", font: { size: 12 } }, ticks: { font: { size: 12 } } },
        y: { stacked: true, ticks: { font: { size: yAxisFontSize } } },
      },
    },
  });
}

function renderCompare() {
  const grid = document.getElementById("compare-grid");
  grid.replaceChildren(...sessions.map((r, i) => {
    const m = computeSessionMetrics(r);
    const cacheCreationTitle = "Includes a source that does not report cache-creation tokens (agy) - this session's real cost may be higher than shown."
    const cacheCreationRow = includeCacheCreation
      ? `<dt>Cache creation${m.cacheCreationFullyMeasured ? "" : " ⚠"}</dt><dd${m.cacheCreationFullyMeasured ? "" : ` title="${cacheCreationTitle}"`}>${m.cacheCreation.toLocaleString()}</dd>`
      : "";
    // Only shown when at least one event in the session has a confidence_score
    // (confidence-analysis was run and recorded for it) — most sessions won't,
    // so the row is absent rather than showing "–" everywhere. When the
    // session mixes scored and unscored events (a group, or partial
    // validation), the partial-coverage note makes that explicit instead of
    // presenting an average as if every item were scored.
    const confidenceRow = m.confidenceScore == null
      ? ""
      : `<dt title="${m.confidenceScoredCount < m.requests ? `Average of ${m.confidenceScoredCount}/${m.requests} scored requests — the rest have no confidence-analysis score yet.` : "confidence-analysis score, 0-10"}">Confidence score${m.confidenceScoredCount < m.requests ? " ⚠" : ""}</dt><dd>${m.confidenceScore.toFixed(1)}/10</dd>`;

    const card = document.createElement("div");
    card.className = "metric-card";
    card.innerHTML = `
      <div class="name"><span class="swatch" style="background:${PALETTE[i % PALETTE.length]}"></span>${escapeHtml(r.label)}</div>
      <dl>
        <dt>Requests</dt><dd>${m.requests.toLocaleString()}</dd>
        <dt>Sessions</dt><dd>${m.sessions.toLocaleString()}</dd>
        <dt>Total tokens</dt><dd>${m.totalTokens.toLocaleString()}</dd>
        <dt>Cache miss</dt><dd>${m.tokensSemCacheRead.toLocaleString()}</dd>
        ${cacheCreationRow}
        <dt>Tokens/request</dt><dd>${m.requests ? Math.round(m.totalTokens / m.requests).toLocaleString() : "–"}</dd>
        <dt>Cache-hit rate</dt><dd>${(m.cacheHitRate * 100).toFixed(1)}%</dd>
        ${confidenceRow}
        <dt title="Weekly agy quota that dropped during this row's time window — a global signal shared by every row in the same window, not specific to this row's tool or events.">agy quota consumed (same window, global)</dt><dd>${(m.quota * 100).toFixed(1)}%</dd>
      </dl>
    `;
    return card;
  }));
}

let modelChart = null;
let sourceChart = null;

function renderBreakdowns() {
  const active = sessions;
  const labels = active.map(r => r.label);

  const models = [...new Set(filteredEvents().map(e => e.model))];
  const modelDatasets = models.map((m, i) => ({
    label: m,
    data: active.map(r => eventsForSession(r).filter(e => e.model === m).reduce((s, e) => s + eventTotalTokens(e), 0)),
    backgroundColor: PALETTE[i % PALETTE.length],
  }));
  if (modelChart) modelChart.destroy();
  modelChart = new Chart(document.getElementById("model-chart"), {
    type: "bar",
    data: { labels, datasets: modelDatasets },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 12, font: { size: 12 } } } },
      scales: { x: { stacked: true, ticks: { font: { size: 11 } } }, y: { stacked: true, ticks: { font: { size: 11 } } } },
    },
  });

  const sources = [...new Set(filteredEvents().map(e => e.source))];
  const sourceDatasets = sources.map((src, i) => ({
    label: src,
    data: active.map(r => eventsForSession(r).filter(e => e.source === src).reduce((s, e) => s + eventTotalTokens(e), 0)),
    backgroundColor: PALETTE[i % PALETTE.length],
  }));
  if (sourceChart) sourceChart.destroy();
  sourceChart = new Chart(document.getElementById("source-chart"), {
    type: "bar",
    data: { labels, datasets: sourceDatasets },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 12, font: { size: 12 } } } },
      scales: { x: { stacked: true, ticks: { font: { size: 11 } } }, y: { stacked: true, ticks: { font: { size: 11 } } } },
    },
  });
}

function renderAll() {
  renderTimeline();
  renderSessionsList();
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
    def api_usage(since: str | None = None, until: str | None = None) -> dict:
        return build_dashboard_payload(store, since=since, until=until)

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
