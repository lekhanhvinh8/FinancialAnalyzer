"""
Live progress for one portfolio run, written to an auto-refreshing HTML file.

WHY NOT progress.RunAllProgress

  That class is shaped for single/median1000, where the unit of work is a symbol
  and each one produces its own result: end_ok() takes a growth figure, a trade
  count and a chart path per symbol. A portfolio run has none of that shape. Its
  symbols are inputs, not results; there is exactly one result at the end; and
  the wall clock is dominated by two phases that are not symbol work at all.

  So the model here is PHASES, not rows:

      1. load     N symbols out of the database        minutes
      2. backtest one pass over the calendar           under a second
      3. charts   one Plotly file per traded symbol    minutes

  Phase 2 is listed even though it is instant, because a reader watching the
  file needs to see it happen — a run that sat between "loading done" and
  "building charts" with nothing in between would look stuck at the exact moment
  it is doing the thing the whole run exists for.

THE ETA IS A RUNNING AVERAGE AND SAYS SO

  Items are not equally expensive — a symbol with 3,800 rows loads slower than
  one with 1,400 — so the estimate is wrong early and settles as it goes. It is
  there to answer "another minute or another ten", not to be accurate, and the
  page labels it with a tilde rather than pretending otherwise.
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
