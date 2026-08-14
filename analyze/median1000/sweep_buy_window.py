"""
Sweep the buy arm's median window against its threshold: BUY_MEDIAN_WINDOW x q.

The buy arm compared the price to a 1000-day median because that number was
hardcoded, never because it was tested. Sell and reinvest stay on 1000 here; only
the buy arm moves.

WHY q AND NOT PERCENT_BUY

  A fixed percentage is not the same condition at different windows. The price's
  distance from its own median widens as the window grows — measured over 59
  symbols and 182,522 observations per window (analyze/median1000/dispersion.py):

      p95 = 1.290 * w^0.698      R^2 = 0.9991      w in 20..1000

  so PERCENT_BUY = 60 is above the entire distribution at w=50 and blocks nothing,
  sits at the 95th percentile at w=250, and blocks about a fifth of days at
  w=1000. A rectangular grid of raw percentages would spend most of its cells on
  "always buys" and "never buys".

  The swept quantity is therefore

      PERCENT_BUY = q * 1.290 * w^0.698

  so a column means roughly one thing at every window: q = 1.0 is the 95th
  percentile of that window's own deviation, q = 0.5 is around the 80th, q = 0
  is "only buy below the median". The live setting, w=1000 with PERCENT_BUY=60,
  is q = 0.37.

  Two known limits, both from dispersion.py:
  - This normalises SCALE, and the centre moves too — the median deviation runs
    from +0.4 at w=50 to +16.8 at w=1000. Columns match well in the upper tail,
    where a buy ceiling actually binds, and drift in the lower half.
  - The constant is fitted on the full history. It decides which cells are worth
    testing, not what the strategy does; the winning cell is a plain fixed pair.

WHAT IT FOUND: THE WINDOW BARELY MATTERS, AND 1000 IS ALREADY FINE

  52 symbols, 500 cells, 30.7 min. Region in the top 10% of BOTH mean and vote:
  w = 500..1000, q = 0.2..0.6, 39 cells.

      w     q    PERCENT_BUY   mean   vote   neighbours in region
    820   0.4           55.8   41.1    471   7/8   interior
    780   0.4           53.9   41.0    467   7/8
   1000   0.4           64.1   40.9    488   2/5   live

  Nothing to change. The live setting is inside the region and 0.2 mean points
  off the best of 500 cells, which is noise. Two independent sweeps now agree.

  The window is close to irrelevant: taking the best cell in each row, the mean
  spans 36.5 to 41.1 across a 50x change in window length. The threshold is what
  moves the result — every one of the top ten cells is q=0.4.

  Its 2/5 neighbours is a grid artefact, not an edge in the surface. w=1000 is
  the last row so it only has five neighbours; the rows below it read 40.6, 40.8,
  40.9, so nothing is falling away.

  The worst symbol sits between -275 and -250 in every cell in the grid. LPB is
  out of reach of this parameter as well.

WHY THE GRID STOPS AT 1000

  The sell arm needs 1000 bars of warmup whatever the buy arm does, so any buy
  window at or below 1000 leaves the start index exactly where it is. Every cell
  then sees the same symbols over the same bars and the whole grid is comparable
  for free. Going above 1000 would move the start, cost symbols, and force a
  fixed start at the longest window.

  That follow-up is NOT needed: the surface is flat at the top, w=740 through
  1000 reading 40.1, 41.1, 40.6, 40.8, 40.9. It would only be worth running if
  the top rows were still climbing.

READING IT

  Same as the other sweeps: mean beside the vote, and check the buy count before
  believing either. Differences are per symbol against the same symbol at another
  cell; a difference of two aggregates would be comparing different symbols.

Usage:
    python analyze/median1000/sweep_buy_window.py             # all symbols
    python analyze/median1000/sweep_buy_window.py FPT STB     # a subset
    python analyze/median1000/sweep_buy_window.py --rescore
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import math
import statistics as st
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

import database as db
from analyze.runner import load_symbol_df, run_estimate
from analyze.median1000 import config
from analyze.median1000.factory import make_median_strategies, make_interval_strategies

WINDOWS = list(range(20, 1001, 20))                        # 50
QS      = [round(-0.2 + 0.2 * i, 1) for i in range(10)]    # -0.2 .. 1.6
#          Round steps so the two interpretable anchors land exactly on a
#          column: q=0 is "only buy below the median", q=1.0 is that
#          window's 95th percentile. Live (w=1000, PERCENT_BUY=60) is q=0.37.

# p95 = C * w^A, from dispersion.py on 59 symbols, w in 20..1000, R^2 = 0.9991.
# Only ever used to place grid points.
P95_C, P95_A = 1.290, 0.698

OUT  = Path(__file__).parent / "sweep_buy_window.html"
RAW  = Path(__file__).parent / "sweep_buy_window_raw.json"
PROG = Path(__file__).parent / "sweep_buy_window_progress.html"


def percent_buy(q: float, w: int) -> float:
    return q * P95_C * (w ** P95_A)


def _key(w, q):
    return f"{w}|{q}"


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, buys, sells)}, note)."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"

        # Every swept window plus the 1000 the sell arm needs, in one query.
        crc = db.load_range_stats(sym, df, range_days=set(WINDOWS) | {1000})
        if not crc:
            return sym, None, "no range_stats"

        d2i = {pd.Timestamp(r["time"]): i for i, r in df.iterrows()}

        def sig(window, col):
            d = db.load_trend_signals(sym, window_days=window)
            out = {}
            if not d.empty:
                for dt, v in d[col].items():
                    i = d2i.get(pd.Timestamp(dt))
                    if i is not None:
                        out[i] = float(v)
            return out

        s3 = sig(1000, "signal3_sharpe") if config.MIN_SIGNAL3 is not None else {}
        s1 = (sig(config.SELL_SIGNAL1_WINDOW, "signal1_slope")
              if config.SELL_MIN_SIGNAL1 is not None else {})
        ri = (s1 if (s1 and config.REINVEST_SIGNAL1_WINDOW == config.SELL_SIGNAL1_WINDOW)
              else (sig(config.REINVEST_SIGNAL1_WINDOW, "signal1_slope")
                    if config.REINVEST_MIN_SIGNAL1 is not None else {}))
        z = {}
        if config.SELL_MIN_ZDEV is not None:
            zd = db.load_zdev(sym, 1000, config.SELL_ZDEV_WINDOW)
            if zd.empty:
                return sym, None, f"no z_dev at stat_window={config.SELL_ZDEV_WINDOW}"
            for dt, v in zd["z_dev"].items():
                i = d2i.get(pd.Timestamp(dt))
                if i is not None and v is not None:
                    z[i] = float(v)

        # One start index for every cell, and it does not depend on the swept
        # window because the grid stops at 1000 and the sell arm needs that
        # anyway. Every cell is therefore judged on identical bars.
        start_idx = max([1000] + [min(m) for m in (s1, s3, ri, z) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        for w in WINDOWS:
            for q in QS:
                buy, sell, rei = make_median_strategies(
                    signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                    zdev_map=z, percent_buy=percent_buy(q, w), buy_window=w)
                r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei,
                                 crc, start_index=start_idx)
                out[_key(w, q)] = (round(r["allRatioGrowth"] - base, 4),
                                   r["totalBuys"], r["totalSells"])
        return sym, out, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {e}"


def apply_exclusions(per_symbol: dict) -> dict:
    drop = {s.upper() for s in getattr(config, "EXCLUDE_SYMBOLS", [])}
    hit = sorted(drop & {s.upper() for s in per_symbol})
    if not hit:
        return per_symbol
    kept = {s: d for s, d in per_symbol.items() if s.upper() not in drop}
    print(f"  EXCLUDE_SYMBOLS {hit}: {len(per_symbol)} -> {len(kept)} symbols")
    return kept


def aggregate(per_symbol: dict) -> dict:
    """{metric: {key: value}} — mean, vote, buys, sells, win, worst."""
    keys = [_key(w, q) for w in WINDOWS for q in QS]
    syms = [s for s in per_symbol if all(k in per_symbol[s] for k in keys)]
    grids = {m: {} for m in ("mean", "median", "win", "worst", "vote", "buys", "sells")}
    if not syms:
        return grids

    m = np.array([[per_symbol[s][k][0] for k in keys] for s in syms])
    # Round robin, one vote per symbol: immune to a single dominant symbol, and
    # blind to size. Read it beside the mean, never instead of it.
    for i, k in enumerate(keys):
        col = m[:, i][:, None]
        grids["vote"][k] = int(((col - m > 1e-9).sum(axis=0)
                                > (m - col > 1e-9).sum(axis=0)).sum())
    for i, k in enumerate(keys):
        vals = sorted(m[:, i].tolist())
        grids["mean"][k] = st.mean(vals)
        grids["median"][k] = st.median(vals)
        grids["win"][k] = 100 * sum(1 for v in vals if v > 0) / len(vals)
        grids["worst"][k] = vals[0]
        grids["buys"][k] = st.mean([per_symbol[s][k][1] for s in syms])
        grids["sells"][k] = st.mean([per_symbol[s][k][2] for s in syms])
    return grids


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {"windows": WINDOWS, "qs": QS, "elapsed": elapsed,
                 "p95": [P95_C, P95_A],
                 "config": {c: getattr(config, c) for c in dir(config)
                            if c.isupper() and not c.startswith("_")}},
        "skipped": skipped, "results": per_symbol,
    }), encoding="utf-8")


def load_raw():
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    per = {s: {k: tuple(v) for k, v in d.items()} for s, d in raw["results"].items()}
    return per, [tuple(x) for x in raw["skipped"]], raw["meta"].get("elapsed", 0.0)


def write_progress(done, total, started, note=""):
    el = time.time() - started
    pct = 100 * done / total if total else 0
    eta = (el / done * (total - done)) if done else 0
    PROG.write_text(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>buy window sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>buy window sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(WINDOWS)}&times;{len(QS)}
= {len(WINDOWS)*len(QS)}</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


METRICS = {
    "mean":   ("Mean diff",    "%", +1),
    "vote":   ("Cells beaten", "",  +1),
    "median": ("Median diff",  "%", +1),
    "win":    ("Win rate",     "%", +1),
    "worst":  ("Worst symbol", "%", +1),
    "buys":   ("Buys",         "",  0),
    "sells":  ("Sells",        "",  0),
}


def build_html(grids, n_syms, skipped, elapsed):
    live_w = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
    live_q = config.PERCENT_BUY / (P95_C * live_w ** P95_A) if config.PERCENT_BUY else 0.0

    rows = ""
    for m, (label, unit, direction) in METRICS.items():
        g = grids.get(m) or {}
        if not g or direction == 0:
            continue
        bk, bv = max(g.items(), key=lambda kv: kv[1])
        w, q = bk.split("|")
        rows += (f"<tr><td style='text-align:left'>{label}</td>"
                 f"<td><b>w={w}, q={q}</b></td>"
                 f"<td>PERCENT_BUY = {percent_buy(float(q), int(w)):.0f}</td>"
                 f"<td style='color:#4ade80'>{bv:+.2f}{unit}</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    data = {m: {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in (grids.get(m) or {}).items()} for m in METRICS}
    opts = "".join(f"<option value='{m}'{' selected' if m == 'mean' else ''}>{lbl}</option>"
                   for m, (lbl, _, _) in METRICS.items())

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>buy window sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:11px;margin:10px 0}}
th,td{{border:1px solid #1e293b;padding:4px 6px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:960px}}
select{{background:#111c30;color:#e2e8f0;border:1px solid #334155;padding:6px 10px;
  border-radius:6px;font-size:14px}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
  padding:12px 16px;margin:12px 0;display:inline-block}}
.wrap{{overflow-x:auto}}
</style></head><body>
<h2>Buy arm: median window &times; threshold</h2>
<p class="note">{n_syms} symbols, {len(WINDOWS)}&times;{len(QS)} =
{len(WINDOWS)*len(QS)} cells, {elapsed/60:.1f} min. Sell and reinvest stay on the
1000-day median; only the buy arm moves. The threshold is
<code>PERCENT_BUY = q &times; {P95_C} &times; w^{P95_A}</code>, so a column is
roughly constant strictness at every window &mdash; q=1.0 is that window's 95th
percentile of price-to-median distance, q=0 is &ldquo;only buy below the
median&rdquo;.<br>Live: <b>w={live_w}, PERCENT_BUY={config.PERCENT_BUY}</b>
(q &asymp; {live_q:.2f}).</p>
{skip_html}
<div class="card"><b>What each metric prefers</b>
<table><thead><tr><th>metric</th><th>best cell</th><th>threshold</th>
<th>value</th></tr></thead><tbody>{rows}</tbody></table>
<span class="note">Mean follows the largest symbol; vote gives every symbol one
vote and is blind to size. A cell that wins only one of them is telling you which
way it leans.</span></div>

<p><b>Heat map:</b> <select id="metric">{opts}</select></p>
<div class="wrap"><table id="grid"></table></div>
<p class="note"><b>Read the plateau, not the best cell.</b> The best of
{len(WINDOWS)*len(QS)} cells looks good whether or not any edge exists.</p>

<script>
const DATA = {json.dumps(data)};
const WS = {json.dumps(WINDOWS)}, QS = {json.dumps(QS)};
// Cell keys are built in Python and shipped as strings. Letting JS join them with
// w + '|' + q silently drops whole-valued q: Python writes "1000|1.0" and JS
// stringifies 1.0 as "1", so those columns render blank. It cost q=0 and q=1 here
// before anyone noticed.
const QK = {json.dumps([str(q) for q in QS])};
function render() {{
  const m = document.getElementById('metric').value;
  const g = DATA[m];
  const vals = Object.values(g).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  let h = '<thead><tr><th>w</th>';
  QS.forEach(q => {{ h += '<th>q=' + q + '</th>'; }});
  h += '</tr></thead><tbody>';
  WS.forEach(function(w) {{
    h += "<tr><th style='text-align:right'>" + w + '</th>';
    QS.forEach(function(q, j) {{
      const v = g[w + '|' + QK[j]];
      if (v === null || v === undefined) {{
        h += "<td style='color:#475569'>&mdash;</td>"; return;
      }}
      const f = hi === lo ? 0.5 : (v - lo) / (hi - lo);
      const bg = f >= 0.5
        ? 'rgba(34,197,94,' + (0.10 + 0.62 * (f - 0.5) * 2).toFixed(2) + ')'
        : 'rgba(239,68,68,' + (0.10 + 0.62 * (0.5 - f) * 2).toFixed(2) + ')';
      const txt = (m === 'vote') ? v.toFixed(0)
                : (m === 'buys' || m === 'sells') ? v.toFixed(0)
                : (v >= 0 ? '+' : '') + v.toFixed(0);
      h += "<td style='background:" + bg + "'>" + txt + '</td>';
    }});
    h += '</tr>';
  }});
  document.getElementById('grid').innerHTML = h + '</tbody>';
}}
document.getElementById('metric').addEventListener('change', render);
render();
</script>
</body></html>"""


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded"); return
    grids = aggregate(per_symbol)
    OUT.write_text(build_html(grids, len(per_symbol), skipped, elapsed),
                   encoding="utf-8")

    g = grids["mean"]
    print(f"\nmean diff, {len(per_symbol)} symbols")
    print(f"{'w':>5} " + " ".join(f"{q:>6g}" for q in QS))
    for w in WINDOWS:
        print(f"{w:>5} " + " ".join(f"{g.get(_key(w,q), float('nan')):6.0f}" for q in QS))

    print("\nwhat each metric prefers:")
    for m, (label, unit, d) in METRICS.items():
        gg = grids.get(m) or {}
        if not gg or d == 0:
            continue
        bk, bv = max(gg.items(), key=lambda kv: kv[1])
        w, q = bk.split("|")
        print(f"  {label:<14} w={w:<5} q={q:<6} "
              f"PERCENT_BUY={percent_buy(float(q), int(w)):7.1f}  -> {bv:+.2f}{unit}")

    live_w = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
    lq = min(QS, key=lambda q: abs(percent_buy(q, live_w) - config.PERCENT_BUY))
    lk = _key(live_w, lq)
    if lk in g:
        print(f"\nnearest cell to live (w={live_w}, PERCENT_BUY={config.PERCENT_BUY}): "
              f"q={lq} -> mean {g[lk]:+.1f}, vote {grids['vote'][lk]}")
    print(f"\nreport -> {OUT}")


def main():
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--rescore" in flags:
        if not RAW.exists():
            print(f"no raw data at {RAW} — run the sweep first"); return
        per, skipped, elapsed = load_raw()
        print(f"re-scoring {len(per)} symbols from {RAW.name}")
        _report(per, skipped, elapsed)
        return

    syms = [s.upper() for s in args] or db.list_symbols()
    print(f"Sweeping {len(WINDOWS)}x{len(QS)} = {len(WINDOWS)*len(QS)} cells "
          f"over {len(syms)} symbols")
    t0 = time.time()
    per_symbol, skipped, done = {}, [], 0
    write_progress(0, len(syms), t0, "starting workers…")
    print(f"progress -> {PROG}")

    with ProcessPoolExecutor() as ex:
        futures = {ex.submit(eval_symbol, s): s for s in syms}
        for fut in as_completed(futures):
            sym, res, note = fut.result()
            done += 1
            if res is None:
                skipped.append((sym, note))
                print(f"[{done}/{len(syms)}] {sym} skipped — {note}", flush=True)
            else:
                per_symbol[sym] = res
                print(f"[{done}/{len(syms)}] {sym} ok", flush=True)
            write_progress(done, len(syms), t0, f"last: {sym}")

    if not per_symbol:
        print("nothing to report"); return
    elapsed = time.time() - t0
    save_raw(per_symbol, skipped, elapsed)
    print(f"raw -> {RAW}")
    _report(per_symbol, skipped, elapsed)
    print(f"({elapsed/60:.1f} min)   re-score with: "
          f"python {Path(__file__).name} --rescore")


if __name__ == "__main__":
    main()
