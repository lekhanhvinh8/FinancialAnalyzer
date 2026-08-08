"""Live progress trackers — writes auto-refreshing HTML files."""

import json
import time
from datetime import datetime
from pathlib import Path


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="3">
<title>Sync Progress</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0f1117; color: #e2e8f0;
  font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px;
  padding: 24px; min-height: 100vh;
}
h1 { font-size: 20px; font-weight: 700; }
.header { display: flex; align-items: center; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }
.badge {
  display: inline-block; padding: 3px 10px; border-radius: 12px;
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
}
.badge-running { background: #1d4ed8; color: #bfdbfe; }
.badge-done    { background: #14532d; color: #86efac; }
.badge-force   { background: #7c2d12; color: #fed7aa; }
.meta { color: #64748b; font-size: 13px; }
.meta b { color: #94a3b8; font-weight: 500; }
.section { margin-top: 28px; }
.section-title {
  font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1px; color: #475569; margin-bottom: 12px;
}
/* ── Step cards ── */
.steps-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
.step-card {
  background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 8px; padding: 14px 16px;
}
.step-card.active  { border-color: #3b82f6; }
.step-card.done-c  { border-color: #22c55e44; opacity: 0.8; }
.step-card.pending { opacity: 0.5; }
.step-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.step-name { font-weight: 600; font-size: 13px; }
.step-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.bar-bg { background: #2a2d3a; border-radius: 4px; height: 5px; overflow: hidden; margin-bottom: 7px; }
.bar-fill { height: 100%; border-radius: 4px; }
.step-counts { color: #64748b; font-size: 12px; display: flex; gap: 6px; }
.cnt-done  { color: #22c55e; }
.cnt-error { color: #ef4444; }
.cnt-total { color: #475569; }
.cnt-pct   { margin-left: auto; color: #64748b; }
/* ── Current ── */
.current-card {
  background: #1a1d27; border: 1px solid #2563eb; border-radius: 8px;
  padding: 14px 18px; display: flex; align-items: center; gap: 14px;
}
.spinner {
  width: 18px; height: 18px; border-radius: 50%; border: 2px solid;
  border-top-color: transparent !important; flex-shrink: 0;
  animation: spin 0.75s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.cur-label { font-size: 12px; color: #64748b; margin-bottom: 3px; }
.cur-path  { font-size: 15px; font-weight: 600; }
.cur-arrow { color: #334155; margin: 0 5px; font-weight: 400; }
.cur-since { font-size: 12px; color: #475569; margin-top: 3px; }
.no-cur    { color: #475569; font-style: italic; padding: 10px 0; }
/* ── Log table ── */
.log-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th {
  text-align: left; padding: 8px 12px; color: #475569;
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
  border-bottom: 1px solid #1e2130; white-space: nowrap;
}
td { padding: 7px 12px; border-bottom: 1px solid #161924; color: #94a3b8; white-space: nowrap; }
tr:hover td { background: #1a1d27; }
td.sym  { color: #e2e8f0; font-weight: 500; }
td.mono { font-family: monospace; color: #64748b; }
td.note { color: #3f4f66; font-size: 12px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.tag {
  display: inline-block; padding: 1px 8px; border-radius: 10px;
  font-size: 11px; font-weight: 600; background: #1e2130;
}
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
</style>
</head>
<body>
<script>
const D = __DATA__;

const COLORS = {
  prices: "#3b82f6", shares: "#a855f7", profit: "#f59e0b",
  pe: "#22c55e", "range-stats": "#06b6d4", outputs: "#f97316"
};
const c = s => COLORS[s] || "#94a3b8";

function dur(s) {
  if (s == null) return "—";
  if (s < 60) return s.toFixed(1) + "s";
  return Math.floor(s/60) + "m " + Math.round(s%60) + "s";
}
function elapsed(s) {
  if (s < 60) return Math.round(s) + "s";
  const m = Math.floor(s/60);
  if (m < 60) return m + "m " + Math.round(s%60) + "s";
  return Math.floor(m/60) + "h " + (m%60) + "m";
}

const running = D.status === "running";
const cur = D.current;
const curStep = cur ? cur.step : null;

// ── Header ──
let h = `<div class="header">
  <h1>PriceToEarn Sync</h1>
  <span class="badge badge-${running ? "running" : "done"}">${running ? "⟳ Running" : "✓ Done"}</span>
  ${D.force ? '<span class="badge badge-force">Force</span>' : ""}
  <span class="meta">Started <b>${D.started_at}</b></span>
  <span class="meta">Elapsed <b>${elapsed(D.elapsed_s)}</b></span>
  <span class="meta">Indices <b>${D.indices.join(", ").toUpperCase()}</b></span>
</div>`;

// ── Steps ──
h += `<div class="section"><div class="section-title">Steps</div><div class="steps-grid">`;
for (const step of D.steps) {
  const t = D.step_totals[step] || {total: 0, done: 0, error: 0, skip: 0};
  const completed = t.done + t.error + t.skip;
  const pct = t.total > 0 ? Math.round(completed / t.total * 100) : 0;
  const isActive = step === curStep;
  const isDone   = !isActive && t.total > 0 && completed >= t.total;
  const isPending = !isActive && !isDone && completed === 0;
  const col = c(step);
  const dotCol = isActive ? col : isDone ? "#22c55e" : "#2a2d3a";
  h += `<div class="step-card ${isActive ? "active" : isDone ? "done-c" : isPending ? "pending" : ""}">
    <div class="step-header">
      <span class="step-name">${step}</span>
      <span class="step-dot" style="background:${dotCol}"></span>
    </div>
    <div class="bar-bg"><div class="bar-fill" style="width:${pct}%;background:${col}"></div></div>
    <div class="step-counts">
      <span class="cnt-done">${t.done}</span>
      ${t.error > 0 ? `<span class="cnt-error">/ ${t.error} err</span>` : ""}
      <span class="cnt-total">/ ${t.total}</span>
      <span class="cnt-pct">${pct}%</span>
    </div>
  </div>`;
}
h += `</div></div>`;

// ── Current ──
h += `<div class="section"><div class="section-title">Currently Running</div>`;
if (cur) {
  const col = c(cur.step);
  h += `<div class="current-card">
    <div class="spinner" style="border-color:${col}"></div>
    <div>
      <div class="cur-label">${cur.step} › ${cur.index.toUpperCase()}</div>
      <div class="cur-path" style="color:${col}">${cur.symbol}</div>
      <div class="cur-since">since ${cur.started_at}</div>
    </div>
  </div>`;
} else if (running) {
  h += `<div class="no-cur">Preparing next item…</div>`;
} else {
  h += `<div class="no-cur">Finished at ${D.finished_at || "—"}</div>`;
}
h += `</div>`;

// ── Log ──
h += `<div class="section"><div class="section-title">Event Log (${D.events.length} items)</div>`;
if (D.events.length === 0) {
  h += `<div class="no-cur">No events yet…</div>`;
} else {
  h += `<div class="log-wrap"><table>
    <thead><tr>
      <th>Time</th><th>Step</th><th>Index</th><th>Symbol</th>
      <th>Status</th><th>Duration</th><th>Note</th>
    </tr></thead><tbody>`;
  for (const ev of D.events.slice(0, 150)) {
    const col = c(ev.step);
    const dotCol = ev.status === "done" ? "#22c55e" : ev.status === "error" ? "#ef4444" : "#475569";
    h += `<tr>
      <td class="mono">${ev.time.split(" ")[1]}</td>
      <td><span class="tag" style="color:${col}">${ev.step}</span></td>
      <td>${ev.index.toUpperCase()}</td>
      <td class="sym">${ev.symbol}</td>
      <td><span class="dot" style="background:${dotCol}"></span>${ev.status}</td>
      <td class="mono">${dur(ev.duration_s)}</td>
      <td class="note">${ev.note || ""}</td>
    </tr>`;
  }
  h += `</tbody></table></div>`;
}
h += `</div>`;

document.body.innerHTML = h;
</script>
</body>
</html>"""


class SyncProgress:
    def __init__(self, steps: set, indices: list, force: bool):
        self._start = time.time()
        self.data = {
            "started_at":  _now(),
            "updated_at":  _now(),
            "finished_at": None,
            "elapsed_s":   0,
            "force":       force,
            "steps":       sorted(steps),
            "indices":     indices,
            "status":      "running",
            "current":     None,
            "events":      [],
            "step_totals": {},
        }
        self._flush()

    def set_totals(self, step: str, total: int):
        self.data["step_totals"][step] = {"total": total, "done": 0, "error": 0, "skip": 0}
        self._flush()

    def begin(self, step: str, index: str, symbol: str):
        self.data["current"] = {"step": step, "index": index, "symbol": symbol, "started_at": _now()}
        self._flush()

    def end(self, step: str, index: str, symbol: str,
            duration_s: float, status: str = "done", note: str = ""):
        self.data["current"] = None
        self.data["events"].insert(0, {
            "time": _now(), "step": step, "index": index, "symbol": symbol,
            "status": status, "duration_s": round(duration_s, 1), "note": note,
        })
        t = self.data["step_totals"].get(step)
        if t and status in t:
            t[status] += 1
        self._flush()

    def finish(self):
        self.data["status"]      = "done"
        self.data["finished_at"] = _now()
        self.data["current"]     = None
        self._flush()

    def _flush(self):
        self.data["updated_at"] = _now()
        self.data["elapsed_s"]  = round(time.time() - self._start, 1)
        data_json = json.dumps(self.data, ensure_ascii=False)
        Path("sync_progress.json").write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        Path("sync_progress.html").write_text(
            _HTML.replace("__DATA__", data_json), encoding="utf-8"
        )


# ─────────────────────────────────────────────────────────────────────────────
# RunAllProgress
# ─────────────────────────────────────────────────────────────────────────────

_RUN_ALL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="3">
<title>Run All Progress</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0f1117; color: #e2e8f0;
  font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px;
  padding: 24px; min-height: 100vh;
}
h1 { font-size: 20px; font-weight: 700; }
.header { display: flex; align-items: center; gap: 14px; margin-bottom: 24px; flex-wrap: wrap; }
.badge {
  display: inline-block; padding: 3px 10px; border-radius: 12px;
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
}
.badge-running { background: #1d4ed8; color: #bfdbfe; }
.badge-done    { background: #14532d; color: #86efac; }
.meta { color: #64748b; font-size: 13px; }
.meta b { color: #94a3b8; font-weight: 500; }
.bar-bg { background: #1e293b; border-radius: 6px; height: 8px; overflow: hidden; margin-bottom: 20px; }
.bar-fill { height: 100%; border-radius: 6px; background: #3b82f6; transition: width 0.4s; }
.section { margin-top: 24px; }
.section-title {
  font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1px; color: #475569; margin-bottom: 10px;
}
.cur-card {
  background: #1a1d27; border: 1px solid #2563eb; border-radius: 8px;
  padding: 12px 18px; display: flex; align-items: center; gap: 14px;
}
.spinner {
  width: 18px; height: 18px; border-radius: 50%;
  border: 2px solid #3b82f6; border-top-color: transparent;
  flex-shrink: 0; animation: spin 0.75s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.cur-sym  { font-size: 16px; font-weight: 700; color: #60a5fa; }
.cur-sub  { font-size: 12px; color: #475569; margin-top: 3px; }
.no-cur   { color: #475569; font-style: italic; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th {
  text-align: left; padding: 8px 12px; color: #475569;
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
  border-bottom: 1px solid #1e2130; white-space: nowrap;
  position: sticky; top: 0; background: #0f1117;
}
td { padding: 6px 12px; border-bottom: 1px solid #161924; color: #94a3b8; white-space: nowrap; }
tr:hover td { background: #1a1d27; }
td.sym { color: #e2e8f0; font-weight: 600; }
td.err { color: #ef4444; font-style: italic; }
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
</style>
</head>
<body>
<script>
const D = __DATA__;

function elapsed(s) {
  if (s < 60) return Math.round(s) + "s";
  const m = Math.floor(s / 60);
  if (m < 60) return m + "m " + Math.round(s % 60) + "s";
  return Math.floor(m / 60) + "h " + (m % 60) + "m";
}
function pctColor(v) {
  if (v === null) return "";
  if (v >= 200) return "background:#166534;color:#bbf7d0";
  if (v >= 100) return "background:#14532d;color:#d1fae5";
  if (v >= 50)  return "background:#365314;color:#ecfccb";
  if (v >= 0)   return "background:#422006;color:#fef3c7";
  return "background:#7f1d1d;color:#fee2e2";
}

// Diff is signed, so it gets its own scale: sign matters, magnitude is secondary.
// pctColor's absolute bands would read a -5% diff the same as a -300% one.
function diffColor(v) {
  if (v === null) return "color:#64748b";
  if (v > 0)  return "color:#4ade80;font-weight:700";
  if (v < 0)  return "color:#f87171;font-weight:700";
  return "color:#94a3b8";
}

const done  = D.results.length + D.errors.length;
const total = D.total;
const pct   = total > 0 ? Math.round(done / total * 100) : 0;
const running = D.status === "running";

// Header
let h = `<div class="header">
  <h1>Run All — Backtest</h1>
  <span class="badge badge-${running ? "running" : "done"}">${running ? "⟳ Running" : "✓ Done"}</span>
  <span class="meta">Started <b>${D.started_at}</b></span>
  <span class="meta">Elapsed <b>${elapsed(D.elapsed_s)}</b></span>
  <span class="meta"><b>${done} / ${total}</b> symbols</span>
</div>`;

// Progress bar
h += `<div class="bar-bg"><div class="bar-fill" style="width:${pct}%"></div></div>`;

// Current
h += `<div class="section"><div class="section-title">Currently Processing</div>`;
if (D.current) {
  h += `<div class="cur-card">
    <div class="spinner"></div>
    <div>
      <div class="cur-sym">${D.current.symbol}</div>
      <div class="cur-sub">started ${D.current.started_at}</div>
    </div>
  </div>`;
} else {
  h += `<div class="no-cur">${running ? "Preparing…" : "Finished at " + (D.finished_at || "—")}</div>`;
}
h += `</div>`;

// Results table
h += `<div class="section"><div class="section-title">Results (${D.results.length} completed)</div>`;
if (D.results.length === 0 && D.errors.length === 0) {
  h += `<div class="no-cur">No results yet…</div>`;
} else {
  h += `<table><thead><tr>
    <th>#</th><th>Symbol</th>
    <th>Median growth</th><th>Buys</th><th>Sells</th><th>Reinvests</th>
    <th>Interval growth</th><th>Diff</th><th>Chart</th><th>Duration</th>
  </tr></thead><tbody>`;
  D.results.forEach((r, i) => {
    const ms = pctColor(r.median_growth);
    const is = pctColor(r.interval_growth);
    const dv = (r.median_growth !== null && r.interval_growth !== null)
             ? r.median_growth - r.interval_growth : null;
    h += `<tr>
      <td style="color:#475569">${i+1}</td>
      <td class="sym">${r.symbol}</td>
      <td style="${ms};text-align:right;padding:6px 12px">${r.median_growth !== null ? r.median_growth.toFixed(2) + "%" : "—"}</td>
      <td style="text-align:right">${r.buys}</td>
      <td style="text-align:right">${r.sells}</td>
      <td style="text-align:right">${r.reinvests}</td>
      <td style="${is};text-align:right;padding:6px 12px">${r.interval_growth !== null ? r.interval_growth.toFixed(2) + "%" : "—"}</td>
      <td style="${diffColor(dv)};text-align:right;padding:6px 12px">${dv !== null ? (dv >= 0 ? "+" : "") + dv.toFixed(2) + "%" : "—"}</td>
      <td><a href="${r.chart}" target="_blank">open</a></td>
      <td style="color:#475569">${r.duration_s.toFixed(1)}s</td>
    </tr>`;
  });
  D.errors.forEach(e => {
    h += `<tr><td style="color:#475569">—</td><td class="sym">${e.symbol}</td>
      <td class="err" colspan="8">${e.note}</td></tr>`;
  });
  h += `</tbody></table>`;
}
h += `</div>`;

document.body.innerHTML = h;
</script>
</body>
</html>"""


class RunAllProgress:
    def __init__(self, symbols: list, out: str = "charts/run_all_progress.html"):
        self._start   = time.time()
        self._out     = Path(out)
        self._out.parent.mkdir(exist_ok=True)
        self.data = {
            "started_at":  _now(),
            "updated_at":  _now(),
            "finished_at": None,
            "elapsed_s":   0,
            "status":      "running",
            "total":       len(symbols),
            "current":     None,
            "results":     [],
            "errors":      [],
        }
        self._flush()

    def begin(self, symbol: str):
        self.data["current"] = {"symbol": symbol, "started_at": _now()}
        self._flush()

    def end_ok(self, symbol: str, duration_s: float,
               median_growth: float, buys: int, sells: int, reinvests: int,
               interval_growth: float, chart: str):
        self.data["current"] = None
        self.data["results"].append({
            "symbol":          symbol,
            "median_growth":   median_growth,
            "buys":            buys,
            "sells":           sells,
            "reinvests":       reinvests,
            "interval_growth": interval_growth,
            "chart":           chart,
            "duration_s":      round(duration_s, 1),
        })
        self._flush()

    def end_err(self, symbol: str, note: str):
        self.data["current"] = None
        self.data["errors"].append({"symbol": symbol, "note": note[:120]})
        self._flush()

    def finish(self):
        self.data["status"]      = "done"
        self.data["finished_at"] = _now()
        self.data["current"]     = None
        self._flush()

    def _flush(self):
        self.data["updated_at"] = _now()
        self.data["elapsed_s"]  = round(time.time() - self._start, 1)
        self._out.write_text(
            _RUN_ALL_HTML.replace("__DATA__", json.dumps(self.data, ensure_ascii=False)),
            encoding="utf-8",
        )
