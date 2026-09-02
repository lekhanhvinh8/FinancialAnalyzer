"""
Progress pages: a run writing what it is doing to an auto-refreshing HTML file.

THREE CLASSES, THREE SHAPES OF RUN. They are not variants of each other and
merging them would mean inventing a shape none of the callers has:

    RunProgress      named PHASES with optional per-item steps -- load, compute,
                     backtest, report. Used by portfolio/ and breadth/.
    RunAllProgress   one row per SYMBOL, each ending with its result, so a long
                     parallel sweep can be read while it runs. Used by the
                     single/ methods.
    SyncProgress     one row per sync STEP per symbol. Used by sync.py.

WHY ONE MODULE. Two files held these -- one at the project root -- so a reader
had to know which import to reach for and the root of the project carried a
utility. One module, one import, and the HTML shell they all write is in one
place to be changed.
"""

import json
import time
from datetime import datetime
from html import escape
from pathlib import Path


class RunProgress:
    """
    Written to disk on every update, so the file is readable while the run is
    still going. That is the whole point: a progress file that is only correct
    at the end is a log.
    """

    def __init__(self, out: Path, phases: list):
        """`phases` is [(key, label, total), ...]; total None means unknown."""
        self.out = Path(out)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.time()
        self.phases = [{"key": k, "label": l, "total": t, "done": 0,
                        "status": "pending", "items": [], "started": None,
                        "elapsed": 0.0}
                       for k, l, t in phases]
        self.status = "running"
        self.note = ""
        self.summary: dict = {}
        self.flush()

    def _phase(self, key):
        for p in self.phases:
            if p["key"] == key:
                return p
        raise KeyError(key)

    def begin(self, key, note=""):
        p = self._phase(key)
        p["status"] = "running"
        p["started"] = time.time()
        self.note = note
        self.flush()

    def step(self, key, label, ok=True, detail=""):
        p = self._phase(key)
        p["done"] += 1
        p["elapsed"] = time.time() - (p["started"] or self.started)
        # Newest first: a reader watching a long run cares about what just
        # happened, not what happened ten minutes ago.
        p["items"].insert(0, {"label": label, "ok": ok, "detail": detail})
        del p["items"][60:]
        self.flush()

    def end(self, key, note=""):
        p = self._phase(key)
        p["status"] = "done"
        p["elapsed"] = time.time() - (p["started"] or self.started)
        if note:
            self.note = note
        self.flush()

    def finish(self, summary: dict, report: str = ""):
        self.status = "done"
        self.summary = dict(summary)
        if report:
            self.summary["report"] = report
        self.flush()

    def fail(self, message: str):
        self.status = "failed"
        self.note = message
        self.flush()

    # ── rendering ────────────────────────────────────────────────────────────

    def flush(self):
        self.out.write_text(self._html(), encoding="utf-8")

    def _html(self) -> str:
        elapsed = time.time() - self.started
        blocks = []
        for p in self.phases:
            total, done = p["total"], p["done"]
            pct = (done / total * 100) if total else (100 if p["status"] == "done" else 0)
            eta = ""
            if p["status"] == "running" and total and done:
                eta = f"còn ~{p['elapsed'] / done * (total - done):.0f}s"
            elif p["status"] == "done":
                eta = f"{p['elapsed']:.0f}s"
            count = f"{done}/{total}" if total else ("xong" if p["status"] == "done" else "")
            items = "".join(
                f'<li class="{"ok" if i["ok"] else "bad"}">{escape(i["label"])}'
                + (f' <span class="d">{escape(i["detail"])}</span>' if i["detail"] else "")
                + "</li>"
                for i in p["items"])
            blocks.append(f"""
<section class="ph {p['status']}">
  <div class="ph-head">
    <span class="dot"></span>
    <span class="lbl">{escape(p['label'])}</span>
    <span class="cnt">{count}</span>
    <span class="eta">{eta}</span>
  </div>
  <div class="bar"><div class="fill" style="width:{pct:.1f}%"></div></div>
  {f'<ul class="items">{items}</ul>' if items else ''}
</section>""")

        if self.status == "done" and self.summary:
            rows = "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>"
                           for k, v in self.summary.items() if k != "report")
            link = self.summary.get("report", "")
            done_html = (f'<section class="done-box"><h2>Hoàn tất</h2>'
                         f'<table>{rows}</table>'
                         + (f'<p><a href="{escape(link)}">Mở báo cáo →</a></p>'
                            if link else "")
                         + "</section>")
        elif self.status == "failed":
            done_html = f'<section class="done-box bad"><h2>Lỗi</h2><p>{escape(self.note)}</p></section>'
        else:
            done_html = ""

        # Refresh only while running: reloading a finished page every two
        # seconds would fight the reader trying to click the report link.
        refresh = '<meta http-equiv="refresh" content="2">' if self.status == "running" else ""

        return _PAGE.format(
            refresh=refresh, elapsed=f"{elapsed:.0f}",
            status=self.status, note=escape(self.note),
            updated=datetime.now().strftime("%H:%M:%S"),
            blocks="".join(blocks), done=done_html)


_PAGE = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">{refresh}
<title>Portfolio — đang chạy</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--ground:#F4F6FA;--surface:#FFF;--line:#D3DBE7;--ink:#14202F;--ink2:#46566C;
 --ink3:#74839A;--accent:#1F4FD8;--ok:#1C6B4B;--bad:#B03030;--soft:#EDF1F7}}
@media(prefers-color-scheme:dark){{:root{{--ground:#0E141C;--surface:#151D28;
 --line:#2B3949;--ink:#E4EBF4;--ink2:#A3B2C6;--ink3:#7386A0;--accent:#6E9BFF;
 --ok:#5FCC9C;--bad:#F0857D;--soft:#1C2734}}}}
*{{box-sizing:border-box}}
body{{background:var(--ground);color:var(--ink);margin:0;padding:28px 20px 60px;
 font:15px/1.6 "IBM Plex Sans",system-ui,sans-serif}}
.wrap{{max-width:760px;margin:0 auto;display:flex;flex-direction:column;gap:16px}}
h1{{font-size:20px;margin:0}}
.meta{{color:var(--ink3);font-size:12.5px;font-family:"IBM Plex Mono",monospace}}
.ph{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px 16px}}
.ph-head{{display:flex;align-items:center;gap:10px;margin-bottom:9px}}
.dot{{width:9px;height:9px;border-radius:50%;background:var(--ink3);flex:none}}
.ph.running .dot{{background:var(--accent);animation:p 1s infinite}}
.ph.done .dot{{background:var(--ok)}}
@keyframes p{{50%{{opacity:.3}}}}
.lbl{{font-weight:600}}
.cnt,.eta{{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink3)}}
.eta{{margin-left:auto}}
.bar{{height:6px;background:var(--soft);border-radius:3px;overflow:hidden}}
.fill{{height:100%;background:var(--accent);transition:width .3s}}
.ph.done .fill{{background:var(--ok)}}
.items{{list-style:none;margin:10px 0 0;padding:0;max-height:190px;overflow:auto;
 font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--ink2)}}
.items li{{padding:2px 0;border-bottom:1px solid var(--soft)}}
.items li.bad{{color:var(--bad)}}
.items .d{{color:var(--ink3)}}
.done-box{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:16px}}
.done-box h2{{margin:0 0 10px;font-size:17px}}
.done-box.bad h2{{color:var(--bad)}}
.done-box table{{border-collapse:collapse;font-size:13.5px}}
.done-box th{{text-align:left;font-weight:500;color:var(--ink2);padding:3px 18px 3px 0}}
.done-box td{{font-family:"IBM Plex Mono",monospace}}
a{{color:var(--accent)}}
</style></head><body><div class="wrap">
<header>
  <h1>Portfolio — {status}</h1>
  <div class="meta">{elapsed}s · cập nhật {updated}{note}</div>
</header>
{blocks}
{done}
</div></body></html>
"""


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

// In flight — several at once, so one card per worker
const inflight = D.running || [];
h += `<div class="section"><div class="section-title">Currently Processing`;
h += inflight.length > 1 ? ` (${inflight.length} workers)` : ``;
h += `</div>`;
if (inflight.length) {
  for (const r of inflight) {
    h += `<div class="cur-card">
      <div class="spinner"></div>
      <div>
        <div class="cur-sym">${r.symbol}</div>
        <div class="cur-sub">started ${r.started_at}</div>
      </div>
    </div>`;
  }
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
            # A list, not a single "current": run_all works several symbols at
            # once, so there is no one symbol being processed.
            "running":     [],
            "results":     [],
            "errors":      [],
        }
        self._flush()

    def begin(self, symbol: str):
        self.data["running"].append({"symbol": symbol, "started_at": _now()})
        self._flush()

    def _drop_running(self, symbol: str):
        self.data["running"] = [r for r in self.data["running"]
                                if r["symbol"] != symbol]

    def end_ok(self, symbol: str, duration_s: float,
               median_growth: float, buys: int, sells: int, reinvests: int,
               interval_growth: float, chart: str):
        self._drop_running(symbol)
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
        self._drop_running(symbol)
        self.data["errors"].append({"symbol": symbol, "note": note[:120]})
        self._flush()

    def finish(self):
        self.data["status"]      = "done"
        self.data["finished_at"] = _now()
        self.data["running"]     = []
        self._flush()

    def _flush(self):
        self.data["updated_at"] = _now()
        self.data["elapsed_s"]  = round(time.time() - self._start, 1)
        self._out.write_text(
            _RUN_ALL_HTML.replace("__DATA__", json.dumps(self.data, ensure_ascii=False)),
            encoding="utf-8",
        )
