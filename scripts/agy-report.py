#!/usr/bin/env python3
"""Generate a standalone HTML report from the agy usage SQLite database.

Usage:
    agy-report.py [--out report.html]

Reads usage_snapshots (weekly quota, zero-cost /usage polls) and task_calls
(per-task token counts from -p calls), embeds both as JSON in a static HTML
file with Chart.js (CDN), and opens it in the default browser.
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.sqlite_usage_store import SqliteUsageStore

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>agy usage report</title>
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
  .sub { color: GrayText; font-size: 13px; margin-bottom: 24px; }
  .empty { color: GrayText; font-size: 14px; padding: 40px 0; text-align: center; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px; }
  .card { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 8px; padding: 16px; }
  .card h2 { font-size: 13px; margin: 0 0 12px; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent); }
  th { color: GrayText; font-weight: 500; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .filters { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
  .filters select, .filters input { font: inherit; padding: 4px 8px; }
</style>
</head>
<body>
<h1>agy usage report</h1>
<div class="sub" id="generated-at"></div>

<div id="content"></div>

<script>
const SNAPSHOTS = __SNAPSHOTS__;
const CALLS = __CALLS__;

document.getElementById("generated-at").textContent =
  `${SNAPSHOTS.length} quota snapshots · ${CALLS.length} tracked task calls · generated ${new Date().toLocaleString()}`;

if (SNAPSHOTS.length === 0 && CALLS.length === 0) {
  document.getElementById("content").innerHTML =
    '<p class="empty">No data yet. Run agy-snapshot.py (quota) or agy-track.py (task calls) to start collecting.</p>';
} else {
  render();
}

function render() {
  const content = document.getElementById("content");
  content.innerHTML = `
    <div class="grid">
      <div class="card"><h2>Weekly quota remaining over time</h2><canvas id="quota-chart"></canvas></div>
      <div class="card"><h2>Total tokens by model (task calls)</h2><canvas id="model-chart"></canvas></div>
    </div>
    <div class="grid">
      <div class="card"><h2>Tokens per day</h2><canvas id="daily-chart"></canvas></div>
      <div class="card">
        <h2>Recent task calls</h2>
        <table id="calls-table"><thead><tr>
          <th>Time</th><th>Model</th><th class="num">Total tokens</th><th>Task</th>
        </tr></thead><tbody></tbody></table>
      </div>
    </div>
  `;

  renderQuotaChart();
  renderModelChart();
  renderDailyChart();
  renderCallsTable();
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

const PALETTE = ["#7aa2f7", "#9ece6a", "#e0af68", "#f7768e", "#bb9af7", "#7dcfff"];

function renderQuotaChart() {
  if (SNAPSHOTS.length === 0) return;
  const byGroup = groupBy(SNAPSHOTS, s => s.model_group);
  const datasets = [...byGroup.entries()].map(([group, rows], i) => ({
    label: group,
    data: rows.map(r => ({ x: r.timestamp, y: r.remaining_fraction * 100 })),
    borderColor: PALETTE[i % PALETTE.length],
    tension: 0.2,
  }));
  new Chart(document.getElementById("quota-chart"), {
    type: "line",
    data: { datasets },
    options: {
      scales: {
        x: { type: "time", time: { unit: "day" } },
        y: { title: { display: true, text: "% remaining" }, min: 0, max: 100 },
      },
    },
  });
}

function renderModelChart() {
  if (CALLS.length === 0) return;
  const byModel = groupBy(CALLS, c => c.model);
  const labels = [...byModel.keys()];
  const data = labels.map(m => byModel.get(m).reduce((s, c) => s + c.total_tokens, 0));
  new Chart(document.getElementById("model-chart"), {
    type: "bar",
    data: { labels, datasets: [{ label: "Total tokens", data, backgroundColor: PALETTE[0] }] },
    options: { indexAxis: "y" },
  });
}

function renderDailyChart() {
  if (CALLS.length === 0) return;
  const byDay = groupBy(CALLS, c => c.timestamp.slice(0, 10));
  const days = [...byDay.keys()].sort();
  const data = days.map(d => byDay.get(d).reduce((s, c) => s + c.total_tokens, 0));
  new Chart(document.getElementById("daily-chart"), {
    type: "bar",
    data: { labels: days, datasets: [{ label: "Total tokens", data, backgroundColor: PALETTE[1] }] },
  });
}

function renderCallsTable() {
  const tbody = document.querySelector("#calls-table tbody");
  const recent = [...CALLS].sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 50);
  tbody.replaceChildren(...recent.map(c => {
    const tr = document.createElement("tr");
    const cells = [
      new Date(c.timestamp).toLocaleString(),
      c.model,
      c.total_tokens.toLocaleString(),
      c.task || "",
    ];
    cells.forEach((text, i) => {
      const td = document.createElement("td");
      td.textContent = text;
      if (i === 2) td.className = "num";
      tr.appendChild(td);
    });
    return tr;
  }));
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
        snapshots = [
            {
                "timestamp": s.timestamp,
                "model_group": s.model_group,
                "remaining_fraction": s.remaining_fraction,
                "reset_time": s.reset_time,
            }
            for s in store.list_snapshots()
        ]
        calls = [
            {
                "timestamp": c.timestamp,
                "model": c.model,
                "status": c.status,
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "thinking_tokens": c.thinking_tokens,
                "total_tokens": c.total_tokens,
                "duration_s": c.duration_s,
                "task": c.task,
            }
            for c in store.list_task_calls()
        ]
        return snapshots, calls
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="Output path (default: ~/.cache/ai-tokens-tracker/report.html)")
    parser.add_argument("--no-open", action="store_true", help="Don't open the report in a browser")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else Path.home() / ".cache" / "ai-tokens-tracker" / "report.html"
    out_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    snapshots, calls = fetch_data()
    html = TEMPLATE.replace("__SNAPSHOTS__", _json_for_script(snapshots)).replace(
        "__CALLS__", _json_for_script(calls)
    )
    out_path.write_text(html)
    out_path.chmod(0o600)

    print(f"✓ report written to {out_path}")
    if not args.no_open:
        webbrowser.open(f"file://{out_path}")


if __name__ == "__main__":
    main()
