"""
Sweep the second sell trigger: PERCENT_SELL_BOTTOM.

Sell when the price is this far above the SELL_MEDIAN_WINDOW LOW. In the strategy
it is OR'd with the existing test against the median; in this sweep the median
test is switched OFF in every cell, so the bottom trigger is judged on its own.

WHY THE MEDIAN TEST IS OFF IN THE CELLS

  Left on, the bottom trigger can only ever ADD sells to a condition that already
  catches most of what there is to catch, and the sweep measures an increment
  rather than the idea. Off, the two are a head-to-head: is distance-from-the-low
  a better price test than distance-from-the-median?

  That needed a change in the None convention. PERCENT_SELL = None used to mean
  "replace the arm with SellStrategy and never sell", which would have made the
  bottom threshold unreachable. The arm now has two price triggers, each switches
  off independently, and only both being off falls back to the base class. In the
  shipped config the bottom trigger is None, so PERCENT_SELL = None still means
  "never sell" there and the all-None engine check is unaffected.

  The grid is then homogeneous — one parameter, twelve values plus None — and is
  read the way sweep_percent_sell is read: the reference is a ROW, chosen in the
  browser, defaulting to this parameter's own None. PERCENT_SELL is not a row and
  is not the baseline for anything. It is printed once under the table as context,
  because "is this trigger any good" and "is it better than the median one" are
  different questions and only the first is what this grid answers.

THE FIRST THING HERE THAT LOOSENS THE SELL ARM INSTEAD OF RESTRAINING IT

  Every previous attempt on this arm was a filter, and all three lost the same
  way:

      SELL_MIN_ZDEV                     0 of 66 cells
      PERCENT_SELL x PERCENT_REINVEST   FPT +91, GMD +428  ->  15 up, 34 down
      SELL_MIN_PELOG                    FPT +88, GMD  +96  ->  19 up, 21 down

  Each fixed the symbol it was built for and each charged the rest of the
  portfolio for it. The reading recorded on SellMedian1000Strategy is that this
  arm is net positive, so quieting it pays the majority to rescue the minority.
  That reading has an obvious untested corollary and this is it: if restraining
  the arm costs, does loosening it pay?

  Expect the mirror-image failure mode. A filter can win by never selling; a
  second trigger can lose by selling constantly. Watch the sells column before
  anything else.

WHAT IT CATCHES THAT THE MEDIAN CANNOT

  A symbol that runs away from its floor while the median chases the price up.
  The distance to the median never opens, so the existing condition stays quiet
  the whole way, while the distance to the window low keeps growing.

THE GRID

  Measured over 58 symbols and 124,382 post-warmup observations:

      p5     p25     p50     p75     p95     p99
      14      70     132     227     488     986      price vs 1000-bar low
     -26       0      24      60     172     386      price vs 1000-bar median

  The two are on completely different scales — the low is a floor, so the
  distance to it is large and one-sided, while the median sits in the middle. A
  threshold that reads as huge next to PERCENT_SELL = 75 is not necessarily
  loose here.

  Where the grid is dense is set by where the arm's behaviour actually changes,
  measured as sells per symbol:

      threshold     50    75   100   150   200   250   300   350   400   500   600
      sells       21.4  14.1  12.6   8.8   6.1   3.9   2.8   1.5   1.1   0.5   0.2

  So 150 to 400 is where it goes from churning to quiet, and that is where the
  step is 25. Below it, four coarse points to show the collapse; above it, 450 and
  500 plus one near-inert anchor at 600, by which point 52 of 58 symbols never
  trigger it at all.

  An earlier grid ran to 1000. Those cells were dead weight — at 800 and 1000 the
  arm sells 0.08 and 0.02 times per symbol, which is the None row with extra
  steps.

COSTS NO WARMUP

  local_bottom comes out of the same range_stats row the median already does, so
  every cell shares the start index run_all would use anyway, so no row is judged
  on more bars than another.

Usage:
    python analyze/median1000/sweep_sell_bottom.py             # all symbols
    python analyze/median1000/sweep_sell_bottom.py FPT GMD     # a subset
    python analyze/median1000/sweep_sell_bottom.py --rescore
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
from analyze.median1000.factory import (make_median_strategies,
                                        make_interval_strategies, build_pelog_map)

# Coarse at the edges, dense through the middle, one near-inert anchor at the top
# — the same shape sweep_percent_sell uses, and dense over the same thing: the
# stretch where the sell count falls from many to few. Here that is 150 to 400,
# where sells run 8.8 down to 1.1 per symbol.
QS = ([50, 75, 100, 125]
      + list(range(150, 401, 25))
      + [450, 500, 600])                                            # 18

# The reference is this parameter's own None, exactly as sweep_percent_sell pairs
# against the live value of the parameter it sweeps. With the median trigger off
# in every cell, None here means the arm never sells, so the grid is homogeneous:
# one parameter, one of whose settings happens to be "no trigger at all".
#
# PERCENT_SELL is deliberately NOT the reference. Pairing the bottom trigger
# against a median-based configuration measures which of two different price
# tests is better, which is a different question from what this grid answers —
# is this trigger any good, and at what value. The live median config is still
# computed and printed, but as a footnote outside the grid, never as the baseline.
NOSELL_KEY = "none"
LIVE_KEY   = "live"      # context only, not part of the grid

OUT  = Path(__file__).parent / "sweep_sell_bottom.html"
RAW  = Path(__file__).parent / "sweep_sell_bottom_raw.json"
PROG = Path(__file__).parent / "sweep_sell_bottom_progress.html"


def _key(q):
    return f"{q}"


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, reinvests, buys, sells)}, note)."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"

        buy_w  = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
        sell_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
        pe_w   = getattr(config, "PE_MEDIAN_WINDOW", 500)
        windows = {1000, buy_w, sell_w}
        if config.SELL_MIN_PELOG is not None:
            windows.add(pe_w)
        crc = db.load_range_stats(symbol=sym, df=df, range_days=windows)
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

        # Every gate stays exactly as configured — this sweep moves the price
        # test, not the filters. A gate that is off is not loaded, so its warmup
        # cannot push the start index for something nobody is applying.
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
        pl = {}
        if config.SELL_MIN_PELOG is not None:
            pl = build_pelog_map(sym, df, crc, pe_w)
            if not pl:
                return sym, None, f"no usable P/E at window={pe_w}"

        start_idx = max([1000, buy_w, sell_w]
                        + [min(m) for m in (s1, s3, ri, z, pl) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        def cell(pct_sell, pct_bottom):
            buy, sell, rei = make_median_strategies(
                signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                zdev_map=z, pelog_map=pl,
                percent_sell=pct_sell, percent_sell_bottom=pct_bottom)
            r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                             start_index=start_idx)
            # (diff, reinvests, buys, sells) — the order sweep_percent_sell,
            # sweep_percent_reinvest and sweep_min_signal3 all use.
            return (round(r["allRatioGrowth"] - base, 4), r["totalReinvest"],
                    r["totalBuys"], r["totalSells"])

        out = {NOSELL_KEY: cell(None, None),                  # this grid's None
               LIVE_KEY:   cell(config.PERCENT_SELL, None)}   # context footnote
        # Median trigger OFF in every swept cell, so the bottom one is judged on
        # its own rather than as an increment on top of a condition that already
        # catches most of what there is to catch.
        for q in QS:
            out[_key(q)] = cell(None, q)
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
    """
    {metric: {key: value}}.

    paired  median per-symbol difference against the None row. The HTML lets the
            reader re-reference any row and recomputes this client-side from the
            per-symbol numbers; this server-side copy is what the console prints.
            Never subtract two aggregate columns instead: changing the threshold
            reorders the symbols, so the symbol at the median of one column is
            not the symbol at the median of the other.
    pairp   sign-test p over decided symbols only.
    nb      how many of the cell's two grid neighbours also beat None
            significantly. One dimension, so the most it can be is 2.
    """
    keys = [NOSELL_KEY, LIVE_KEY] + [_key(q) for q in QS]
    syms = [s for s in per_symbol if all(k in per_symbol[s] for k in keys)]
    grids = {m: {} for m in ("mean", "median", "win", "worst", "vote",
                             "paired", "pairp", "nb", "buys", "sells", "reis")}
    if not syms:
        return grids

    m = np.array([[per_symbol[s][k][0] for k in keys] for s in syms])
    for i, k in enumerate(keys):
        col = m[:, i][:, None]
        grids["vote"][k] = int(((col - m > 1e-9).sum(axis=0)
                                > (m - col > 1e-9).sum(axis=0)).sum())
    for i, k in enumerate(keys):
        vals = sorted(m[:, i].tolist())
        grids["mean"][k]   = st.mean(vals)
        grids["median"][k] = st.median(vals)
        grids["win"][k]    = 100 * sum(1 for v in vals if v > 0) / len(vals)
        grids["worst"][k]  = vals[0]
        grids["reis"][k]   = st.mean([per_symbol[s][k][1] for s in syms])
        grids["buys"][k]   = st.mean([per_symbol[s][k][2] for s in syms])
        grids["sells"][k]  = st.mean([per_symbol[s][k][3] for s in syms])

    base = m[:, keys.index(NOSELL_KEY)]
    for i, k in enumerate(keys):
        d = m[:, i] - base
        up  = int((d > 1e-9).sum())
        dec = int((np.abs(d) > 1e-9).sum())
        grids["paired"][k] = float(np.median(d))
        grids["pairp"][k] = (
            sum(math.comb(dec, j) for j in range(up, dec + 1)) / 2 ** dec
            if dec else 1.0)
    good = {k for k in keys if grids["paired"][k] > 0 and grids["pairp"][k] < 0.05}
    for j, q in enumerate(QS):
        nb = ([QS[j - 1]] if j > 0 else []) + ([QS[j + 1]] if j < len(QS) - 1 else [])
        grids["nb"][_key(q)] = sum(1 for x in nb if _key(x) in good)
    grids["nb"][NOSELL_KEY] = grids["nb"][LIVE_KEY] = 0
    return grids


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {
            # Positional layout of every cell tuple. Two orders grew up across these
            # sweeps and they differ only by position, so a reader that assumes the
            # wrong one reports buys as reinvests and says nothing.
            "fields": ["diff", "reinvests", "buys", "sells"],
            "qs": QS, "elapsed": elapsed,
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
<meta http-equiv="refresh" content="3"><title>sell-bottom sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>second sell trigger sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(QS)} + off</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(grids, per_symbol, n_syms, skipped, elapsed):
    """
    Same shape as sweep_percent_sell's report, and for the same reason: one
    parameter, a homogeneous grid, and the reference chosen in the browser rather
    than baked in.

    PERCENT_SELL is not a row. This grid answers "is this trigger any good, and at
    what value", which is a question about one parameter; putting a median-based
    configuration in it would silently turn every comparison into "is the bottom
    trigger better than the median one", a different question. It is printed once
    below the table as context and takes no part in any figure.
    """
    syms = sorted(per_symbol)
    keys = [NOSELL_KEY] + [_key(q) for q in QS]
    # Per-symbol diffs in one fixed symbol order, shipped so the reference row can
    # change client-side. Subtracting two already-computed vs values would be
    # median(A-ref) - median(B-ref) — the same trap one level up — so the browser
    # always goes back to these.
    diffs = {k: [per_symbol[s][k][0] for s in syms] for k in keys}

    def best(metric):
        g = {k: v for k, v in (grids.get(metric) or {}).items() if k in keys}
        return max(g, key=g.get) if g else None
    bests = {m: best(m) for m in ("mean", "median", "win", "vote", "worst")}

    body = ""
    for k in keys:
        label = ("<b>None</b> <span style='color:#64748b'>no trigger</span>"
                 if k == NOSELL_KEY else k)
        cells = ""
        for m, fmt in (("mean", "{:+.1f}"), ("median", "{:+.1f}"), ("win", "{:.0f}%"),
                       ("vote", "{:.0f}"), ("worst", "{:+.1f}")):
            v = grids[m].get(k, float("nan"))
            hi = " style='color:#4ade80;font-weight:600'" if bests.get(m) == k else ""
            cells += "<td" + hi + ">" + fmt.format(v) + "</td>"
        sells = grids["sells"].get(k, float("nan"))
        churn = " style='color:#fbbf24;font-weight:600'" if sells > 5 else ""
        body += (
            "<tr data-row='" + str(k) + "' style='cursor:pointer'>"
            "<td style='text-align:left'>" + str(label) + "</td>" + cells
            + "<td data-vs='" + str(k) + "' style='border-left:2px solid #334155'></td>"
            + "<td data-vsmeta='" + str(k) + "' style='color:#64748b;font-size:11px'></td>"
            + "<td>" + f"{grids['reis'].get(k, float('nan')):.1f}" + "</td>"
            + "<td>" + f"{grids['buys'].get(k, float('nan')):.0f}" + "</td>"
            + "<td" + churn + ">" + f"{sells:.2f}" + "</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""
    lp  = getattr(config, "PERCENT_SELL", 75)
    lm  = grids["mean"].get(LIVE_KEY, float("nan"))
    lmd = grids["median"].get(LIVE_KEY, float("nan"))
    lw  = grids["worst"].get(LIVE_KEY, float("nan"))
    ls  = grids["sells"].get(LIVE_KEY, float("nan"))

    head = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>PERCENT_SELL_BOTTOM sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #1e293b;padding:5px 10px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
tr[data-row]:hover td{{background:rgba(255,255,255,0.04)}}
tr.refrow td{{background:rgba(96,165,250,0.10)}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:1000px}}
code{{color:#e2e8f0}}
</style></head><body>
<h2>PERCENT_SELL_BOTTOM sweep</h2>
<p class="note">{n_syms} symbols, {len(QS)} settings plus None, {elapsed/60:.1f} min.
One parameter only — the gates and everything else stay at their configured
values, and <b>the median trigger is switched off in every row</b>, so this
measures the bottom trigger on its own and PERCENT_SELL never enters a figure.<br>
The condition is <code>(price&nbsp;&minus;&nbsp;low)/low&nbsp;&times;&nbsp;100
&gt; PERCENT_SELL_BOTTOM</code> against the 1000-bar low. Larger is
<b>stricter</b> and sells less, the same direction as PERCENT_SELL.
<code>None</code> is no trigger at all, which with the median one off means the
arm never sells.<br>
Scale note: the low is a floor, so distance to it is one-sided and large — the
median day sits +132% above it. A number that looks enormous beside PERCENT_SELL
is not necessarily loose.</p>
{skip_html}
<table><thead><tr><th>PERCENT_SELL_BOTTOM</th><th>mean</th><th>median</th><th>win</th>
<th>vote</th><th>worst</th><th style='border-left:2px solid #334155'>vs <span id='refLabel'>None</span></th>
<th>up / p</th><th>reinv</th><th>buys</th><th>sells</th>
</tr></thead><tbody>{body}</tbody></table>
<p class="note"><b>Click any row to make it the reference</b> — the vs column
recomputes against it from the per-symbol numbers. That is the only way to compare
two settings: subtracting two vs values would be
median(A&minus;ref)&nbsp;&minus;&nbsp;median(B&minus;ref), the same mistake one
level up.<br>
<b>median</b>, <b>win</b> and <b>worst</b> must never be subtracted between rows —
the symbol at the median of one column is a different symbol from the one at the
median of another. <b>mean</b> is the exception and may be subtracted: it is
linear. <b>vote</b> is already a pairwise round robin.<br>
<b>sells</b> turns <span style="color:#fbbf24">amber</span> past 5 per symbol. A
second trigger can look good purely by trading constantly, so read it before the
vs column.</p>
<p class="note" style="border-top:1px solid #1e293b;padding-top:10px">
<b>Context, not a row and not a baseline.</b> The live median condition
(PERCENT_SELL = {lp}, no bottom trigger) scores mean {lm:+.1f}, median {lmd:+.1f},
worst {lw:+.1f}, {ls:.2f} sells. Kept out of the grid on purpose: mixing it in
would turn every comparison here into "which of two price tests is better", which
is a different question from the one this grid asks.</p>
"""

    script = """
<script>
const DIFFS = __DIFFS__;
const KEYS  = __KEYS__;
const NONE_KEY = __NONE__;
let   REF   = NONE_KEY;

function med(a) {
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function lchoose(n, k) {
  let r = 0;
  for (let i = 1; i <= k; i++) r += Math.log(n - k + i) - Math.log(i);
  return r;
}
function signP(up, dec) {
  let c = 0;
  for (let k = up; k <= dec; k++) c += Math.exp(lchoose(dec, k) - dec * Math.LN2);
  return Math.min(1, c);
}
function recompute() {
  const ref = DIFFS[REF];
  if (!ref) return;
  document.getElementById('refLabel').textContent = REF === NONE_KEY ? 'None' : REF;
  KEYS.forEach(function(k) {
    const cell = document.querySelector('td[data-vs="' + k + '"]');
    const meta = document.querySelector('td[data-vsmeta="' + k + '"]');
    if (!cell) return;
    if (k === REF) {
      cell.innerHTML = '&mdash;'; cell.style.color = '#64748b';
      meta.textContent = 'reference'; return;
    }
    const d   = DIFFS[k].map((v, i) => v - ref[i]);
    const up  = d.filter(x => x > 1e-9).length;
    const dec = d.filter(x => Math.abs(x) > 1e-9).length;
    const p   = dec ? signP(up, dec) : 1;
    const m   = med(d);
    cell.textContent = (m >= 0 ? '+' : '') + m.toFixed(2);
    cell.style.color = (m > 0 && p < 0.05) ? '#4ade80'
                     : (m < 0 && p > 0.95) ? '#f87171' : '#e2e8f0';
    meta.textContent = up + '/' + dec + '  p=' + p.toFixed(3);
  });
  document.querySelectorAll('tr[data-row]').forEach(function(tr) {
    tr.classList.toggle('refrow', tr.dataset.row === REF);
  });
}
document.querySelectorAll('tr[data-row]').forEach(function(tr) {
  tr.addEventListener('click', function() { REF = tr.dataset.row; recompute(); });
});
recompute();
</script>
</body></html>"""
    script = (script.replace("__DIFFS__", json.dumps(diffs))
                    .replace("__KEYS__", json.dumps([str(k) for k in keys]))
                    .replace("__NONE__", json.dumps(NOSELL_KEY)))
    return head + script


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded"); return
    grids = aggregate(per_symbol)
    pr, pp, nb = grids["paired"], grids["pairp"], grids["nb"]
    if not grids["mean"]:
        print("no symbol has every cell — was the raw file written by an older "
              "version of this script? re-run the sweep."); return

    print(f"\nreference   None, no trigger at all (the median trigger is off in "
          f"every cell)\n            mean {grids['mean'][NOSELL_KEY]:+.2f}  "
          f"median {grids['median'][NOSELL_KEY]:+.2f}  "
          f"sells {grids['sells'][NOSELL_KEY]:.2f}")
    print(f"\ncontext     live median condition, PERCENT_SELL="
          f"{getattr(config, 'PERCENT_SELL', 75)}  <- NOT the baseline\n"
          f"            mean {grids['mean'][LIVE_KEY]:+.2f}  "
          f"median {grids['median'][LIVE_KEY]:+.2f}  "
          f"sells {grids['sells'][LIVE_KEY]:.2f}")

    print(f"\n{'threshold':>10}{'paired':>9}{'p':>8}{'nb':>4}{'mean':>8}{'median':>8}"
          f"{'vote':>6}{'worst':>9}{'sells':>7}")
    for q in QS:
        k = _key(q)
        print(f"{q:>10}{pr[k]:+9.2f}{pp[k]:8.3f}{nb[k]:4d}{grids['mean'][k]:8.1f}"
              f"{grids['median'][k]:8.1f}{grids['vote'][k]:6d}{grids['worst'][k]:9.1f}"
              f"{grids['sells'][k]:7.2f}")

    good = sorted(((pr[_key(q)], q) for q in QS
                   if pr[_key(q)] > 0 and pp[_key(q)] < 0.05), reverse=True)
    print(f"\ncells beating None with p<0.05: {len(good)}/{len(QS)}")
    for v, q in good:
        sl = grids['sells'][_key(q)]
        print(f"  {q:>5}  paired {v:+.2f}  p {pp[_key(q)]:.3f}  nb {nb[_key(q)]}  "
              f"mean {grids['mean'][_key(q)]:+.1f}  sells {sl:.2f}"
              f"{'   <-- CHURN' if sl > 5 else ''}")
    if good:
        solid = [q for _, q in good if nb[_key(q)] >= 2]
        print(f"  with both neighbours agreeing: {len(solid)}"
              f"{' — ' + ', '.join(str(q) for q in solid) if solid else ' (isolated cells only)'}")
    print(f"  cells whose paired median is exactly 0.00: "
          f"{sum(1 for q in QS if abs(pr[_key(q)]) < 1e-9)}/{len(QS)}")

    OUT.write_text(build_html(grids, per_symbol, len(per_symbol),
                              skipped, elapsed),
                   encoding="utf-8")
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
    print(f"Sweeping {len(QS)} thresholds + off over {len(syms)} symbols")
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
