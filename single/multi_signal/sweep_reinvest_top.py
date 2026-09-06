"""
Sweep the second reinvest trigger: PERCENT_REINVEST_TOP.

Redeploy the reserve once the price has fallen this far from the 1000-bar HIGH.
In the strategy it is AND'd with the existing test against the median; in this
sweep the median test is switched OFF in every cell, so the top condition is
judged on its own and PERCENT_REINVEST never enters a figure.

  THIS SWEEP PREDATES THE AND. It ran when the two were OR'd, and every figure
  below is still valid because the median test is off in every cell — with one
  condition live the join does not apply. What changed is what it implies about
  the SHIPPED config, where PERCENT_REINVEST is 10: adding a top threshold there
  now REMOVES reinvests rather than adding them.

SIGN

  Same comparison direction as PERCENT_REINVEST — redeploy while dev is BELOW the
  threshold — but measured against the top, where dev is always <= 0. So the
  threshold is negative and -30 reads as "at least 30% off the high". One rule for
  both triggers, one formula, opposite signs because the reference points sit on
  opposite sides of the price.

WHY THIS MIGHT WORK WHERE WIDENING PERCENT_REINVEST DID NOT

  The dead zone is the underlying problem. After a sell at +75% over the median
  the price must fall 65 points before the money may return, and on a compounder
  it never does, so the 400-bar timeout ends up buying back higher than it sold —
  five of seven re-entries across FPT and GMD, at +20% to +53% above the sell.

  Widening PERCENT_REINVEST was the obvious fix and it lost, 15 symbols up against
  34 down, because it lets money back in UNCONDITIONALLY: on a symbol whose price
  simply stayed high, it redeploys into strength. A drawdown condition is
  selective — it opens only after a real fall from the peak.

  Measured on those same seven re-entries, bars until each condition first permits
  a buy-back, against the timeout's 400:

      sell            dev vs top   median<=10   top<=-30   top<=-40
      FPT 2015-11-03      0.0%        1101        1101       2583
      FPT 2018-01-29     -2.9%         538         538       2020
      FPT 2022-01-19    -11.7%        1022         204       1026
      FPT 2025-04-18    -27.7%         215         112        219
      GMD 2017-03-07      0.0%         332         286        726
      GMD 2021-06-17      0.0%         950         355        951
      GMD 2023-02-03     -8.9%         543         542        544

  At -30, four of the seven happen on the price condition rather than the clock,
  and far sooner: 204 bars instead of 1022, 355 instead of 950. The three it does
  not reach are the ones that sold AT the high — dev vs top 0.0% — where the top
  keeps chasing the price and the gap never opens. That is the compounder case
  again, and this does not solve it.

THE RISK, AND IT IS MEASURABLE

  By construction the days this adds are days the price is still at least 10%
  ABOVE its own median: if the median condition already fired there would be
  nothing to add. So it buys into a fall that has not finished being expensive.
  Whether being conditional on a drawdown is selective enough to beat the
  unconditional widening that already failed is the whole question.

THE GRID

  The existing condition already fires on 35.7% of days, so what matters is how
  many the new one ADDS. Measured over 58 symbols and 124,382 post-warmup
  observations:

      threshold      -10    -20    -30    -40    -50    -60
      extra days    42.3%  21.7%   8.6%   2.3%   0.0%   0.0%     median symbol
      never fires       1      2      7     17     30     47     of 58 symbols

  -10 would take total coverage past three quarters of all days. -50 and below is
  inert for most of the universe. So the step is 2 through -20 to -44, with three
  coarse points above and four below to show both collapses.

  Distribution of the quantity itself, for placing that grid:

      p5     p25    p50    p75    p95
      -61    -39    -23    -11     -1

REFERENCE

  This parameter's own None, the way sweep_percent_sell references the live value
  of what it sweeps. With the median trigger also off, None means the arm never
  redeploys at all — and, because the timeout valve lives on the same class,
  drops that too. It is a low floor and labelled as one. PERCENT_REINVEST is not a
  row; it is printed once under the table as context.

COSTS NO WARMUP

  local_top is on the same range_stats row the median already reads.

WHAT IT FOUND: THE BEST AGGREGATE OF ANY REINVEST SETTING, AND STILL A TIE

  52 symbols, 20 thresholds. Four points to read it against:

      no reinvest at all, timeout included   mean -27.91  median  -0.47
      None: no top trigger, median inert,
            timeout still on   (reference)   mean +24.75  median  +8.50
      best cell, top at -50                  mean +55.79  median +22.04
      live: PERCENT_REINVEST = 10            mean +52.38  median +20.14

  Against the reference, 1 of 20 cells clears p<0.05 and 9 have a paired median of
  exactly 0.00. The one that clears it, -50, does so with a paired median of +0.15
  and no agreeing neighbours.

  Against live, -50 is 21 symbols up and 22 down, paired median +0.00, p=0.620. A
  coin flip. Its aggregate lead comes from three symbols — VND +430, HPG +265,
  HAG +240 — while the typical symbol does not move.

  A ROUND ROBIN SETTLES IT

  Pooling all 35 reinvest configurations from this sweep and sweep_percent_reinvest
  — legitimate because both now run at PERCENT_SELL = 75, and the shared cell
  agrees to 0.0000 on all 52 symbols — and counting how many opponents each beats
  with a positive paired median at p<0.05:

      RI=10 (live)     23 wins    mean 52.38   median 20.14   worst  -90.7
      TOP=-50          21 wins    mean 55.79   median 22.04   worst -121.6
      RI=20            19 wins    mean 48.65   median 14.73
      TOP=-40          17 wins    mean 46.88   median 14.27

  Live wins the round robin. 23 of the 34 others lose to it significantly. Exactly
  one beats it — RI=5, by a paired median of +0.01 at p=0.040, on a mean seven
  points BELOW live. That is a sign test detecting a hundredth of a point, not an
  improvement.

  One thing does separate the two families: every TOP cell has a worst symbol
  around -121 while nearly every RI cell sits at -155.7. The drawdown trigger has
  a consistently better tail. It is the only one of the four new parameters that
  improves anything without a compensating disaster, and still not enough to
  change a setting on.

  THE FIRST RUN OF THIS SWEEP WAS WRONG AND THE MISTAKE IS WORTH KEEPING

  It reported 17 of 20 cells beating the reference with 15 of them having both
  neighbours agree. That reference was built by handing the factory None for both
  price triggers, which falls back to the base class — and the base class has no
  timeout. So the reference lost the 400-bar valve as well as the trigger, while
  every cell kept it. The bare-None floor scored -27.91 against +44.8 for a cell
  at -70 where the top trigger fires almost never: 72 of those points were the
  clock. Isolating a parameter means everything else stays, including the parts
  that live on the same object.

Usage:
    python single/multi_signal/sweep_reinvest_top.py             # all symbols
    python single/multi_signal/sweep_reinvest_top.py FPT GMD     # a subset
    python single/multi_signal/sweep_reinvest_top.py --rescore
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
from single.runner import load_symbol_df, run_estimate
from single.multi_signal import config
from single.multi_signal.factory import (make_median_strategies,
                                        make_interval_strategies, build_pelog_map)
from single.multi_signal.sweep_matrix import matrix_html

# Coarse at the edges, dense through the middle. Dense over -20 to -44 because
# that is where the trigger goes from adding a fifth of all days to adding almost
# none: it contributes 21.7% of extra days at -20, 8.6% at -30, 2.3% at -40 and
# nothing at -50 for the median symbol.
QS = ([-5, -10, -15]
      + list(range(-20, -45, -2))
      + [-50, -55, -60, -70])                                       # 20

# The reference is this parameter's own None, exactly as sweep_percent_sell pairs
# against the live value of the parameter it sweeps. With the median trigger off
# in every cell, None here means the arm never sells, so the grid is homogeneous:
# one parameter, one of whose settings happens to be "no trigger at all".
#
# PERCENT_REINVEST is deliberately NOT the reference. Pairing the top trigger
# against a median-based configuration measures which of two different price
# tests is better, which is a different question from what this grid answers —
# is this trigger any good, and at what value. The live median config is still
# computed and printed, but as a footnote outside the grid, never as the baseline.
# The reference has to isolate the swept parameter, which means everything else
# stays exactly as it is. Handing the factory None for both price triggers does
# NOT do that: it falls back to the base class, which drops the 400-bar timeout
# too, and the timeout is not part of this parameter.
#
# That mistake inflated the first run of this sweep enormously. The bare-None
# reference scored a mean of -27.91 while a cell at -70, where the top trigger
# fires almost never, scored +44.8 — so 72 of those points were the timeout, and
# 17 of 20 cells "beat the reference" mostly by having a clock.
#
# So the reference makes the median trigger INERT rather than absent: -999 means
# "redeploy while the price is 999% below its median", which never happens, and
# the object keeps its timeout. Same sentinel idea as REINVEST_TIMEOUT_PERCENT=999
# on the other side.
INERT = -999
NOSELL_KEY = "none"      # no top trigger, median inert, timeout still on
NOTHING_KEY = "nothing"  # context: no reinvest at all, timeout included
LIVE_KEY   = "live"      # context: the median-based condition as configured

OUT  = Path(__file__).parent / "sweep_reinvest_top.html"
RAW  = Path(__file__).parent / "sweep_reinvest_top_raw.json"
PROG = Path(__file__).parent / "sweep_reinvest_top_progress.html"


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

        def cell(pct_ri, pct_top):
            buy, sell, rei = make_median_strategies(
                signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                zdev_map=z, pelog_map=pl,
                percent_reinvest=pct_ri, percent_reinvest_top=pct_top)
            r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                             start_index=start_idx)
            # (diff, reinvests, buys, sells) — the order sweep_percent_sell,
            # sweep_percent_reinvest and sweep_min_signal3 all use.
            return (round(r["allRatioGrowth"] - base, 4), r["totalReinvest"],
                    r["totalBuys"], r["totalSells"])

        out = {NOSELL_KEY:  cell(INERT, None),                  # this grid's None
               NOTHING_KEY: cell(None, None),                   # context: floor
               LIVE_KEY:    cell(config.PERCENT_REINVEST, None)}  # context: live
        # Median trigger OFF in every swept cell, so the top one is judged on its
        # own rather than as an increment on a condition that already fires on
        # 35.7% of days.
        for q in QS:
            out[_key(q)] = cell(INERT, q)
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
    keys = [NOSELL_KEY, NOTHING_KEY, LIVE_KEY] + [_key(q) for q in QS]
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
    grids["nb"][NOSELL_KEY] = grids["nb"][LIVE_KEY] = grids["nb"][NOTHING_KEY] = 0
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
<h2>reinvest-top sweep &mdash; {'running' if done < total else 'done'}</h2>
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

    PERCENT_REINVEST is not a row. This grid answers "is this trigger any good, and at
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
        sells = grids["reis"].get(k, float("nan"))
        # This arm's churn is redeploying constantly. Live runs 3.96 reinvests per
        # symbol; flag anything past 10.
        churn = " style='color:#fbbf24;font-weight:600'" if sells > 10 else ""
        body += (
            "<tr data-row='" + str(k) + "' style='cursor:pointer'>"
            "<td style='text-align:left'>" + str(label) + "</td>" + cells
            + "<td data-vs='" + str(k) + "' style='border-left:2px solid #334155'></td>"
            + "<td data-vsmeta='" + str(k) + "' style='color:#64748b;font-size:11px'></td>"
            + "<td" + churn + ">" + f"{sells:.2f}" + "</td>"
            + "<td>" + f"{grids['buys'].get(k, float('nan')):.0f}" + "</td>"
            + "<td>" + f"{grids['sells'].get(k, float('nan')):.2f}" + "</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""
    lp  = getattr(config, "PERCENT_REINVEST", 10)
    lm  = grids["mean"].get(LIVE_KEY, float("nan"))
    lmd = grids["median"].get(LIVE_KEY, float("nan"))
    lw  = grids["worst"].get(LIVE_KEY, float("nan"))
    ls  = grids["reis"].get(LIVE_KEY, float("nan"))

    head = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>PERCENT_REINVEST_TOP sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #1e293b;padding:5px 10px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
tr[data-row]:hover td{{background:rgba(255,255,255,0.04)}}
tr.refrow td{{background:rgba(96,165,250,0.10)}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:1000px}}
code{{color:#e2e8f0}}
</style></head><body>
<h2>PERCENT_REINVEST_TOP sweep</h2>
<p class="note">{n_syms} symbols, {len(QS)} settings plus None, {elapsed/60:.1f} min.
One parameter only — the gates and everything else stay at their configured
values, and <b>the median trigger is switched off in every row</b>, so this
measures the top trigger on its own and PERCENT_REINVEST never enters a figure.<br>
The condition is <code>(price&nbsp;&minus;&nbsp;high)/high&nbsp;&times;&nbsp;100
&le; PERCENT_REINVEST_TOP</code> against the 1000-bar high. The quantity is
always &le; 0, so thresholds are negative and &minus;30 reads as &ldquo;at least
30% off the high&rdquo;. <b>More</b> negative is stricter and redeploys less —
the same direction as PERCENT_REINVEST, since both fire while dev is below the
threshold.<br>
<code>None</code> is no trigger at all; with the median one off that means the
arm never redeploys, and it drops the 400-bar timeout with it because that lives
on the same class. It is a low floor and every cell clears it easily — read the
context line under the table, not the vs column alone.</p>
{skip_html}
<table><thead><tr><th>PERCENT_REINVEST_TOP</th><th>mean</th><th>median</th><th>win</th>
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
<b>reinv</b> turns <span style="color:#fbbf24">amber</span> past 10 per symbol,
against the live condition's 3.96. A second trigger can look good purely by
redeploying constantly, so read it before the vs column.</p>
<p class="note" style="border-top:1px solid #1e293b;padding-top:10px">
<b>Context, not a row and not a baseline.</b> The live median-based condition
(PERCENT_REINVEST = {lp}, no top trigger) scores mean {lm:+.1f}, median {lmd:+.1f},
worst {lw:+.1f}, {ls:.2f} reinvests. Kept out of the grid on purpose: mixing it in
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
    # script la chuoi thuong (JS dung { }), nen ghep ma tran o day
    return head + script.replace(
        "</body></html>", matrix_html(per_symbol) + "</body></html>")


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded"); return
    grids = aggregate(per_symbol)
    pr, pp, nb = grids["paired"], grids["pairp"], grids["nb"]
    if not grids["mean"]:
        print("no symbol has every cell — was the raw file written by an older "
              "version of this script? re-run the sweep."); return

    print(f"\nreference   None — no top trigger, median inert, timeout still on\n"
          f"            mean {grids['mean'][NOSELL_KEY]:+.2f}  "
          f"median {grids['median'][NOSELL_KEY]:+.2f}  "
          f"reinvests {grids['reis'][NOSELL_KEY]:.2f}")
    print(f"\ncontext     no reinvest at all, timeout included   "
          f"mean {grids['mean'][NOTHING_KEY]:+.2f}  "
          f"median {grids['median'][NOTHING_KEY]:+.2f}  "
          f"reinvests {grids['reis'][NOTHING_KEY]:.2f}")
    print(f"context     live median-based condition, PERCENT_REINVEST="
          f"{getattr(config, 'PERCENT_REINVEST', 10)}  <- NOT the baseline\n"
          f"            mean {grids['mean'][LIVE_KEY]:+.2f}  "
          f"median {grids['median'][LIVE_KEY]:+.2f}  "
          f"reinvests {grids['reis'][LIVE_KEY]:.2f}")

    print(f"\n{'threshold':>10}{'paired':>9}{'p':>8}{'nb':>4}{'mean':>8}{'median':>8}"
          f"{'vote':>6}{'worst':>9}{'reinv':>7}")
    for q in QS:
        k = _key(q)
        print(f"{q:>10}{pr[k]:+9.2f}{pp[k]:8.3f}{nb[k]:4d}{grids['mean'][k]:8.1f}"
              f"{grids['median'][k]:8.1f}{grids['vote'][k]:6d}{grids['worst'][k]:9.1f}"
              f"{grids['reis'][k]:7.2f}")

    good = sorted(((pr[_key(q)], q) for q in QS
                   if pr[_key(q)] > 0 and pp[_key(q)] < 0.05), reverse=True)
    print(f"\ncells beating None with p<0.05: {len(good)}/{len(QS)}")
    for v, q in good:
        rr = grids['reis'][_key(q)]
        print(f"  {q:>5}  paired {v:+.2f}  p {pp[_key(q)]:.3f}  nb {nb[_key(q)]}  "
              f"mean {grids['mean'][_key(q)]:+.1f}  reinvests {rr:.2f}"
              f"{'   <-- CHURN' if rr > 10 else ''}")
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
