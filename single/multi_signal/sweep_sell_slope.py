"""
Sweep the sell price threshold against the slope gate that vetoes it:
PERCENT_SELL x SELL_MIN_SIGNAL1, slope window fixed at 120 days.

THE HYPOTHESIS

  The slope gate blocks a sell while short-term momentum is still up, on the
  reasoning that a rising price should be left to run. But the two conditions are
  read on the same bar, and they do not turn at the same time: the price clears
  its median threshold at the top of a move, which is exactly when the trailing
  slope is still positive. By the time the slope rolls over enough to release the
  gate, the price has already given back part of the peak the gate was protecting.

  If that is right, the two parameters are not independent. Sell earlier (a lower
  PERCENT_SELL) and the lag costs more, because the gate holds through a larger
  share of the remaining move. Sell later (a higher one) and it costs less. The
  best gate setting would then depend on the price threshold, and vice versa.

WHY THIS NEEDS A GRID AND NOT TWO ROWS

  Both parameters have been swept alone, and each was swept with the other sitting
  at its live value. sweep_sell_signal1 covered window x threshold at
  PERCENT_SELL = 75 and nothing else; converting its k axis through
  min_signal1 = k / sqrt(window), its row at window 120 reads:

      threshold   0.000   0.183   0.228   0.274   0.365
      median diff 13.58   15.64   20.14   20.09   20.09
                                  ^ live

  So at 75 the live setting already sits at the top of a plateau. That is an
  answer about the column through 75, and it says nothing about whether the same
  threshold is best at 60 or at 90 — which is the entire question here.

  The standing reminder that one-dimensional results do not compose is
  sweep_reinvest_2d: two triggers that each tied on their own were worse together
  than either alone, and no pair of 1D sweeps could have predicted it.

POLARITY, WHICH IS EASY TO GET BACKWARDS

  The gate blocks when signal1_slope >= SELL_MIN_SIGNAL1. A HIGHER threshold
  therefore blocks FEWER bars — it is the loose direction, and it is the direction
  the hypothesis above points in. None is not merely a very high threshold: it
  removes the gate entirely, and bars above 0.7 do exist, so the None column is a
  real extra setting rather than the end of the axis.

WHAT MOTIVATES SPENDING THE RUN ON THIS GATE

  diag_sell_gates counted where the sell decision dies across 117,163 bars. The
  slope gate is the single largest killer: 8,234 of the 21,916 bars where the
  price test fires, 38% of them, against the Sharpe gate's 17%. Every one of
  VN30's 24 firings dies there and it has never sold.

  That same diagnostic found the arm has 9,931 permitted bars and makes 122 sells,
  81 to 1, because selling needs shares to sell and re-entry is what governs that.
  This sweep is NOT exposed to that finding. It does not try to create more
  permitted bars; it moves WHICH bar in a run of them is the first one, and the
  first one is the only one that becomes a sell.

THE GRID

      PERCENT_SELL          60 .. 90 by 5, live 75
      SELL_MIN_SIGNAL1      None, 0.0, 0.1, 0.15, 0.183, 0.21, 0.228, 0.25,
                            0.274, 0.32, 0.365. Live 0.228, and the spacing is
                            deliberately uneven — see the comment beside SLOPES
                            for the block rates that set it. In short: past 0.365
                            the gate stops binding at all, so spending columns out
                            there only buys duplicates of None, while the step
                            from 0.228 to 0.274 moved a smoke test by 43 points.

  Live (75, 0.228) is a cell, so it is the reference every other cell is paired
  against. Neither axis moves the warmup — but signal1 is loaded for every cell
  INCLUDING the None column, so the start index is identical across the grid.
  Dropping the load when the gate is off would hand that column extra bars and
  break every comparison in the table; sweep_reinvest_top made exactly that
  mistake with the reinvest timeout and 72 points of an apparent gain turned out
  to be the clock.

WHAT IT FOUND — 54 symbols, 77 cells, run of 2026-08-16

  The hypothesis is not supported, and the grid answers it more flatly than a
  wrong-direction result would have.

  Holding PERCENT_SELL fixed and moving only the gate, the paired median is
  EXACTLY 0.00 in 70 of the 70 comparisons. Not small — zero. Six of the seven
  rows are flat end to end, and no row's best cell beats its own live-slope cell
  at p<0.05. The single cell that clears 0.05 (60|0.183, p=0.049) is one of 70,
  and 3.5 are expected by chance.

  So there is no interaction to find, for the reason that there is no slope effect
  to interact with: at every price threshold from 60 to 90, moving the gate
  anywhere from off to 0.365 leaves the median symbol where it was.

  THE MEAN SAYS THE OPPOSITE, LOUDLY, AND IS WRONG TO LISTEN TO

      within-row mean vs the row's own 0.228 cell
      sell   None      0.1     0.15     0.25    0.365
        60  -25.66   +57.11   +56.46    -8.81   -22.82
        75  -56.95   +13.14   +15.03   -10.28   -29.28
        85  -42.27    +3.85    +7.69    -8.59   -21.93

  Read alone this says tighten the gate hard — the opposite of the hypothesis, and
  worth +57 at PERCENT_SELL = 60. But every one of those cells medians to 0.00, so
  the mean is a handful of symbols and nothing else.

  EVERY FIGURE BELOW EXCLUDES VIX AND VIC

    RAW keeps all 54 symbols so the exclusion can be changed by re-scoring, and
    the first reading of this file forgot to apply it. VIX alone moves -574 points
    between two cells, which is enough to flip the sign of any mean in the table:
    85|0.228 reads mean -1.44 over 54 symbols and +6.68 over the configured 52.
    The medians barely move, which is exactly why the paired median is the metric
    this project scores on — but never quote a mean off the raw file.

  WHAT THE RUN DID CONFIRM, AND IT IS NOT ABOUT THE GATE

      cell         paired median   paired mean   up/dec       p
      80|0.228         +1.67          +3.67       29/35    0.0001
      85|0.228         +1.89          +6.68       29/37    0.0004
      90|0.228         +0.93          +5.87       27/37    0.0038

  PERCENT_SELL moved, gate untouched, and the three form a contiguous band rather
  than one lucky cell. sweep_percent_sell scored 85 at +1.87 on a different grid
  and a different run; this reproduces it at +1.89.

  Cells with a higher median exist — 85|0.25 at +3.92, 85|0.365 and 85|None both
  at +3.78 — but the two loose ones carry paired means of -9.16 and -7.84, so they
  buy their median by moving a few symbols a long way in the wrong direction.
  85|0.25 is positive on both and is the one cell of the three worth a second look.

  WHAT ADOPTING 85 COSTS, STATED PLAINLY

      cell       mean    p25   median    p75    worst   losers   sells
      75|0.228   52.38   0.04   20.14   56.54   -90.68     12     2.35
      85|0.228   59.06   0.04   14.09   75.04   -90.68     12     1.77

  The aggregate median FALLS by 6 while 29 of 37 decided symbols individually
  improve. Both are true and they are not in conflict: median(A) - median(B) is
  not median(A - B), and the paired figure is the one that answers "does this help
  each symbol". What actually happens to the distribution is that the top half
  stretches (p75 +18.5) while the middle sags; p25, the worst symbol and the count
  of losing symbols are all unchanged. Expect report_all's headline median to look
  worse after this change, and expect that to be the shape moving rather than a
  regression. The arm also acts less: 2.35 sells per symbol down to 1.77.

  Sell counts corroborate diag_sell_gates: at PERCENT_SELL = 75 the mean sells per
  symbol runs 1.56 at slope 0.0 to 2.73 with the gate off. Removing the largest
  gate in the chain buys 1.2 extra sells per symbol over fifteen years, because
  re-entry and not the gate is what governs how often there is anything to sell.

Usage:
    python single/multi_signal/sweep_sell_slope.py             # all symbols
    python single/multi_signal/sweep_sell_slope.py FPT GMD     # a subset
    python single/multi_signal/sweep_sell_slope.py --rescore
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
from single.multi_signal.factory import make_median_strategies, make_interval_strategies

SELLS  = [60, 65, 70, 75, 80, 85, 90]                              # 7
SLOPES = [None, 0.0, 0.1, 0.15, 0.183, 0.21, 0.228, 0.25, 0.274,
          0.32, 0.365]                                             # 11
#        Raw threshold units, not the k/sqrt(window) form sweep_sell_signal1 used.
#        The window is fixed here, so that normalisation would be a constant factor
#        and only make the axis harder to read against config.py.
#
#        The spacing is not uniform, and the reason is measured. Share of all bars
#        the gate blocks at window 120, over eight symbols:
#
#            0.000  59.6%    0.183  22.1%    0.274  10.5%    0.500   0.5%
#            0.100  37.7%    0.228  16.1%    0.365   3.3%    0.700   0.0%
#
#        0.7 blocks nothing whatsoever — it is a duplicate of the None column, and
#        a first draft of this grid carried it as a real setting. 0.5 is nearly
#        one too. Both are dropped, and the values they freed went into 0.15..0.32,
#        because a four-symbol smoke test put a cliff between 0.228 and 0.274: at
#        PERCENT_SELL = 70 the paired figure moves from -12.27 to +30.75 across
#        that one step, and beyond 0.274 every column was identical to None. The
#        live setting is sitting on the edge of that cliff, which is exactly the
#        place a grid must be dense rather than at its ends.

LIVE = (config.PERCENT_SELL, config.SELL_MIN_SIGNAL1)

OUT  = Path(__file__).parent / "sweep_sell_slope.html"
RAW  = Path(__file__).parent / "sweep_sell_slope_raw.json"
PROG = Path(__file__).parent / "sweep_sell_slope_progress.html"


def _key(s, r):
    return f"{s}|{r}"


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, buys, sells, reinvests)}, note)."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"

        buy_w  = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
        sell_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
        crc = db.load_range_stats(symbol=sym, df=df,
                                  range_days={1000, buy_w, sell_w})
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

        # A gate that is off is not loaded, so its warmup cannot push the start
        # index forward for a filter nobody is applying.
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

        # Neither swept axis is a window, so this is the same for every cell.
        start_idx = max([1000, buy_w, sell_w]
                        + [min(m) for m in (s1, s3, ri, z) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        for ps in SELLS:
            for k in SLOPES:
                buy, sell, rei = make_median_strategies(
                    signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                    zdev_map=z, percent_sell=ps, min_signal1=k)
                r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei,
                                 crc, start_index=start_idx)
                out[_key(ps, k)] = (round(r["allRatioGrowth"] - base, 4),
                                     r["totalBuys"], r["totalSells"],
                                     r["totalReinvest"])
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


def _neighbours(s, r):
    """The up-to-8 cells around one, in grid coordinates rather than value."""
    i, j = SELLS.index(s), SLOPES.index(r)
    out = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            a, b = i + di, j + dj
            if (di or dj) and 0 <= a < len(SELLS) and 0 <= b < len(SLOPES):
                out.append(_key(SELLS[a], SLOPES[b]))
    return out


def aggregate(per_symbol: dict) -> dict:
    """
    {metric: {key: value}}.

    paired  the median per-symbol difference against the live cell. Never
            subtract two aggregate columns instead: changing a parameter
            reorders the symbols, so the symbol at the median of one column is
            not the symbol at the median of the other.
    pairp   the sign-test p for that difference, over decided symbols only.
    nb      how many of the cell's up-to-8 grid neighbours also beat live
            significantly. The best of 56 cells looks good whether or not any
            edge exists; a cell its neighbours agree with is harder to get by
            luck.
    reis    mean reinvests per symbol. The hypothesis this sweep exists to test
            predicts this rises as the dead zone narrows, because the price
            condition starts firing where only the timeout used to reach.
    """
    keys = [_key(s, r) for s in SELLS for r in SLOPES]
    syms = [s for s in per_symbol if all(k in per_symbol[s] for k in keys)]
    grids = {m: {} for m in ("mean", "median", "win", "worst", "vote",
                             "paired", "pairp", "nb", "buys", "sells", "reis")}
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
        grids["mean"][k]   = st.mean(vals)
        grids["median"][k] = st.median(vals)
        grids["win"][k]    = 100 * sum(1 for v in vals if v > 0) / len(vals)
        grids["worst"][k]  = vals[0]
        grids["buys"][k]   = st.mean([per_symbol[s][k][1] for s in syms])
        grids["sells"][k]  = st.mean([per_symbol[s][k][2] for s in syms])
        grids["reis"][k]   = st.mean([per_symbol[s][k][3] for s in syms])

    live_k = _key(*LIVE)
    if live_k in keys:
        base = m[:, keys.index(live_k)]
        for i, k in enumerate(keys):
            d = m[:, i] - base
            up  = int((d > 1e-9).sum())
            dec = int((np.abs(d) > 1e-9).sum())
            grids["paired"][k] = float(np.median(d))
            grids["pairp"][k] = (
                sum(math.comb(dec, j) for j in range(up, dec + 1)) / 2 ** dec
                if dec else 1.0)
        good = {k for k in keys
                if grids["paired"][k] > 0 and grids["pairp"][k] < 0.05}
        for s in SELLS:
            for r in SLOPES:
                k = _key(s, r)
                grids["nb"][k] = sum(1 for n in _neighbours(s, r) if n in good)
    return grids


def interaction(per_symbol: dict) -> list:
    """
    One row per PERCENT_SELL: [(sell, best_slope, gain, up, down, p, live_slope_gain)].

    The question this sweep exists for, and it is NOT "which cell wins" — the heat
    map already says that, and the best of 63 cells looks good whether or not any
    effect exists.

    It is whether the best slope threshold DEPENDS on the price threshold. Each row
    is scored on its own: the row's best cell is compared against the cell in the
    SAME row at the live slope, so the price threshold is held fixed and only the
    gate moves. Read the best_slope column down the table:

        the same value in every row   no interaction. The two parameters are
                                      separable and sweep_sell_signal1 already
                                      answered this at 75; nothing here is new.
        drifting with PERCENT_SELL    interaction, and in the direction the
                                      hypothesis predicts if lower sell thresholds
                                      prefer looser (higher, or None) gates.

    gain is a paired per-symbol median against that row's live-slope cell, never a
    difference of two aggregates: changing a parameter reorders the symbols, so the
    symbol at the middle of one column is not the symbol at the middle of the other.

    live_slope_gain is the same row's live-slope cell measured against the grid's
    live cell (75, 0.228). It is what separates "this row is better because of the
    gate" from "this row is better because of the price threshold" — without it a
    row that wins purely on PERCENT_SELL reads as a gate finding.
    """
    syms = sorted(per_symbol)

    def med_of_diff(a, b):
        d = [per_symbol[s][a][0] - per_symbol[s][b][0] for s in syms]
        up  = sum(1 for v in d if v >  1e-9)
        dn  = sum(1 for v in d if v < -1e-9)
        dec = up + dn
        p = (sum(math.comb(dec, j) for j in range(up, dec + 1)) / 2 ** dec
             if dec else 1.0)
        return st.median(d), up, dn, p, st.mean(d)

    live_k     = _key(*LIVE)
    live_slope = LIVE[1]
    out = []
    for ps in SELLS:
        row_live = _key(ps, live_slope)
        if row_live not in per_symbol[syms[0]]:
            continue
        cands = [r for r in SLOPES
                 if r != live_slope and _key(ps, r) in per_symbol[syms[0]]]
        if not cands:
            continue
        # Ranked on the paired median against this row's own live-slope cell, which
        # is the only comparison that isolates the gate at this price threshold.
        #
        # The tie-break is not cosmetic. Moving this gate leaves most symbols
        # untouched, so the paired median lands on exactly 0.00 in most cells — on
        # the first full run, in 70 of 70. Ranking on the median alone then makes
        # max() return whichever candidate comes first in SLOPES, and it reported
        # "best slope = None" in every row, which reads as a finding and is nothing
        # but list order. up - dn is what still discriminates inside a dead zone:
        # it is the sign test's own statistic, and it does not collapse when half
        # the sample is unmoved.
        scored = [(r, *med_of_diff(_key(ps, r), row_live)) for r in cands]
        best_r, g, up, dn, p, mn = max(scored, key=lambda t: (t[1], t[2] - t[3]))
        # A row where every candidate medians to 0.00 has no best cell at all, and
        # saying so is the honest output. Reported rather than hidden behind the
        # tie-break above, which only picks the least bad of a flat row.
        flat = all(abs(t[1]) < 1e-9 for t in scored)
        row_vs_live = med_of_diff(row_live, live_k)[0]
        out.append((ps, best_r, g, up, dn, p, row_vs_live, mn, flat))
    return out


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {
            # Positional layout of every cell tuple. Two orders grew up across these
            # sweeps and they differ only by position, so a reader that assumes the
            # wrong one reports buys as reinvests and says nothing.
            "fields": ["diff", "buys", "sells", "reinvests"],
            "sells": SELLS, "slopes": SLOPES, "live": list(LIVE),
                 "elapsed": elapsed,
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
<meta http-equiv="refresh" content="3"><title>PERCENT_SELL x SELL_MIN_SIGNAL1 sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>sell % &times; slope gate sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(SELLS)}&times;{len(SLOPES)}
= {len(SELLS)*len(SLOPES)}</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


METRICS = {
    "mean":   ("Mean diff",           "%", +1),
    "paired": ("Paired vs live",      "%", +1),
    "pairp":  ("Sign-test p",         "",  -1),
    "nb":     ("Neighbours agreeing", "",  +1),
    "vote":   ("Cells beaten",        "",  +1),
    "median": ("Median diff",         "%", +1),
    "win":    ("Win rate",            "%", +1),
    "worst":  ("Worst symbol",        "%", +1),
    "buys":   ("Buys",                "",  0),
    "sells":  ("Sells",               "",  0),
    "reis":   ("Reinvests",           "",  0),
}


def build_html(grids, per_symbol, n_syms, skipped, elapsed):
    rows = ""
    for m, (label, unit, direction) in METRICS.items():
        g = grids.get(m) or {}
        if not g or direction == 0:
            continue
        # direction -1 means lower is better; reporting the sign-test's worst
        # cell as its best is the mistake this guards against.
        bk, bv = (max if direction > 0 else min)(g.items(), key=lambda kv: kv[1])
        s, r = bk.split("|")
        rows += (f"<tr><td style='text-align:left'>{label}</td>"
                 f"<td><b>sell={s}, slope={r}</b></td>"

                 f"<td style='color:#4ade80'>{bv:+.2f}{unit}</td></tr>")

    inter = interaction(per_symbol)
    # Built outside the f-string below: it carries both quote characters, and an
    # f-string cannot reuse its own delimiter inside the braces.
    FLAT_TAG = "&nbsp;<span style='color:#f87171'>flat</span>"
    # Read the best-slope column down the table: one repeated value means the two
    # parameters are separable, a drift means they are not.
    grows = "".join(
        f"<tr><td>{ps}</td><td><b>{br}</b>"
        f"{FLAT_TAG if flat else ''}</td>"
        f"<td style='color:{'#4ade80' if g > 0 and p < 0.05 else '#f87171' if g < 0 else '#e2e8f0'}"
        f";font-weight:600'>{g:+.2f}</td>"
        f"<td style='color:#64748b'>{up}/{up+dn}  p={p:.3f}</td>"
        f"<td style='color:#94a3b8'>{rl:+.2f}</td></tr>"
        for ps, br, g, up, dn, p, rl, mn, flat in inter)
    n_picks = len({r[1] for r in inter})

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    data = {m: {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in (grids.get(m) or {}).items()} for m in METRICS}
    opts = "".join(f"<option value='{m}'{' selected' if m == 'paired' else ''}>{lbl}</option>"
                   for m, (lbl, _, _) in METRICS.items())

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>PERCENT_SELL x SELL_MIN_SIGNAL1 sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:12px;margin:10px 0}}
th,td{{border:1px solid #1e293b;padding:5px 8px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:980px}}
select{{background:#111c30;color:#e2e8f0;border:1px solid #334155;padding:6px 10px;
  border-radius:6px;font-size:14px}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
  padding:12px 16px;margin:12px 12px 12px 0;display:inline-block;vertical-align:top}}
.wrap{{overflow-x:auto}}
code{{color:#e2e8f0}}
</style></head><body>
<h2>PERCENT_SELL &times; SELL_MIN_SIGNAL1</h2>
<p class="note">{n_syms} symbols, {len(SELLS)}&times;{len(SLOPES)} =
{len(SELLS)*len(SLOPES)} cells, {elapsed/60:.1f} min. Everything else stays at its
configured value; only the sell price threshold and the slope gate move, and
neither touches the warmup &mdash; signal1 is loaded for every cell including the
None column, so all {len(SELLS)*len(SLOPES)} share one start index.<br>
<b>What this asks.</b> The gate blocks a sell while momentum is still up, but the
price clears its median threshold at the TOP of a move, which is exactly when the
trailing slope is still positive. By the time the slope releases the gate, part of
the peak it was protecting is gone. If that is right the two are not separable:
a lower PERCENT_SELL should want a looser gate, because the lag then holds through
more of the remaining move.<br>
<b>Polarity.</b> The gate blocks when slope &ge; threshold, so a HIGHER threshold
blocks FEWER bars. None removes the gate entirely, which is not the same as the
top of the axis.<br>
<b>Read the interaction table before the heat map.</b> The heat map's best cell
looks good whether or not any effect exists &mdash; it is the best of
{len(SELLS)*len(SLOPES)}. The question is whether the best slope CHANGES down the
PERCENT_SELL rows. One repeated value means the two are separable and
sweep_sell_signal1 already answered this at 75; a drift is the finding.<br>
Live cell: <b>PERCENT_SELL={LIVE[0]}, SELL_MIN_SIGNAL1={LIVE[1]}</b> &mdash; every
paired figure on the heat map is against it. In the interaction table the gain is
against each row's OWN live-slope cell instead, which is what holds the price
threshold fixed so only the gate moves.</p>
{skip_html}

<div class="card"><b>What each metric prefers</b>
<table><thead><tr><th>metric</th><th>best cell</th>
<th>value</th></tr></thead><tbody>{rows}</tbody></table>
<span class="note">Mean follows the largest symbol; vote gives every symbol one
vote and is blind to size. A cell winning only one of them tells you which.</span>
</div>

<div class="card"><b>Does the best slope depend on PERCENT_SELL?</b>
<table><thead><tr><th>PERCENT_SELL</th><th>best slope</th>
<th>gain vs row's live slope</th><th>up / p</th>
<th>row's live slope vs grid live</th></tr></thead>
<tbody>{grows}</tbody></table>
<span class="note">Read the <b>best slope</b> column downwards. {n_picks} distinct
value{'' if n_picks == 1 else 's'} across {len(SELLS)} rows &mdash; one repeated
value means the two parameters are separable and nothing here is new; a drift is
the interaction this sweep exists to find, and the hypothesis predicts it drifts
LOOSER (higher, or None) as PERCENT_SELL falls.<br>
<b>gain</b> is a paired per-symbol median against the cell in the SAME row at the
live slope, which holds the price threshold fixed so only the gate moves. The last
column is that row's live-slope cell against the grid's live cell, and it is there
to stop a row that wins purely on PERCENT_SELL from reading as a gate finding.
</span></div>

<p><b>Heat map:</b> <select id="metric">{opts}</select>
<span class="note">rows = PERCENT_SELL, columns = SELL_MIN_SIGNAL1</span></p>
<div class="wrap"><table id="grid"></table></div>
<p class="note"><b>Read the plateau, not the best cell.</b> The best of
{len(SELLS)*len(SLOPES)} cells looks good whether or not any edge exists &mdash;
about 3 of them reach p&lt;0.05 by chance alone. Check <i>Neighbours agreeing</i>
before believing any single cell, and check <i>Reinvests</i> to see whether a
winning cell actually changed the re-entry behaviour or just moved the sells.</p>

<script>
const DATA = {json.dumps(data)};
// Labels for display, and the SAME strings Python used to build the keys. Both
// axes carry None, and json.dumps writes that as null: joining null with '|' in
// JS gives "null|-30" while the key is "None|-30", which blanked the entire None
// row and the entire None column — the two the synergy table is built on. Same
// trap as the whole-valued q that blanked columns in the earlier sweeps, so the
// fix is the same: never let JS reconstruct a key.
const SS = {json.dumps([str(x) for x in SELLS])};
const RS = {json.dumps([str(x) for x in SLOPES])};
const LIVE = {json.dumps([str(x) for x in LIVE])};
function render() {{
  const m = document.getElementById('metric').value;
  const g = DATA[m];
  const vals = Object.values(g).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  let h = '<thead><tr><th>sell % \\\\ slope</th>';
  RS.forEach(r => {{ h += '<th>' + r + '</th>'; }});
  h += '</tr></thead><tbody>';
  SS.forEach(function(s) {{
    h += "<tr><th style='text-align:right'>" + s + '</th>';
    RS.forEach(function(r) {{
      const v = g[s + '|' + r];
      if (v === null || v === undefined) {{
        h += "<td style='color:#475569'>&mdash;</td>"; return;
      }}
      const f = hi === lo ? 0.5 : (v - lo) / (hi - lo);
      const bg = f >= 0.5
        ? 'rgba(34,197,94,' + (0.10 + 0.62 * (f - 0.5) * 2).toFixed(2) + ')'
        : 'rgba(239,68,68,' + (0.10 + 0.62 * (0.5 - f) * 2).toFixed(2) + ')';
      const dec = (m === 'pairp') ? 3 : (m === 'vote' || m === 'buys'
                  || m === 'sells' || m === 'reis') ? 1 : 0;
      const txt = (v >= 0 && m !== 'pairp' ? '+' : '') + v.toFixed(dec);
      const live = (s === LIVE[0] && r === LIVE[1]);
      h += "<td style='background:" + bg
         + (live ? ';outline:2px solid #60a5fa;outline-offset:-2px' : '')
         + "' title='median " + s + ", top " + r + "'>"
         + txt + '</td>';
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
    pr, pp, nb = grids["paired"], grids["pairp"], grids["nb"]
    live_k = _key(*LIVE)

    print(f"\nlive cell  PERCENT_SELL={LIVE[0]}, SELL_MIN_SIGNAL1={LIVE[1]}  "
          f"  mean {grids['mean'].get(live_k, float('nan')):+.2f}  "
          f"sells {grids['sells'].get(live_k, float('nan')):.2f}  "
          f"reinvests {grids['reis'].get(live_k, float('nan')):.2f}")

    good = sorted(((pr[k], k) for k in pr if pr[k] > 0 and pp[k] < 0.05), reverse=True)
    print(f"\ncells beating live with p<0.05: {len(good)}/{len(pr)}")
    if good:
        print(f"{'median':>7}{'top':>7}{'paired':>9}{'p':>8}{'nb':>4}"
              f"{'mean':>8}{'vote':>6}{'sells':>7}{'reis':>7}")
        for _, k in good[:15]:
            s, r = k.split("|")
            print(f"{s:>7}{r:>7}{pr[k]:+9.2f}{pp[k]:8.3f}{nb[k]:4d}"
                  f"{grids['mean'][k]:8.1f}{grids['vote'][k]:6d}"
                  f"{grids['sells'][k]:7.2f}{grids['reis'][k]:7.2f}")
        solid = [k for _, k in good if nb[k] >= 4]
        print(f"  with 4+ agreeing neighbours: {len(solid)}"
              f"{' — ' + ', '.join(solid[:6]) if solid else ' (none: isolated cells only)'}")
    print(f"  cells whose paired median is exactly 0.00: "
          f"{sum(1 for k in pr if abs(pr[k]) < 1e-9)}/{len(pr)}")

    inter = interaction(per_symbol)
    print("\ndoes the best slope threshold depend on PERCENT_SELL?")
    print(f"{'sell':>6}{'best slope':>12}{'gain vs row live':>18}{'up/dec':>9}"
          f"{'p':>8}{'row live vs grid live':>23}")
    for ps, br, g, up, dn, pv, rl, mn, flat in inter:
        print(f"{ps:>6}{str(br):>12}{g:>+18.2f}{f'{up}/{up+dn}':>9}{pv:>8.3f}"
              f"{rl:>+23.2f}{'   FLAT (every slope medians to 0.00)' if flat else ''}")
    picks = {r[1] for r in inter}
    print(f"\n  distinct best-slope values across the {len(inter)} rows: "
          f"{len(picks)} — {sorted(picks, key=lambda v: (v is not None, v))}")
    print("  one value everywhere means the two parameters are separable and the "
          "1D sweep already answered this;\n  a drift with PERCENT_SELL is the "
          "interaction this sweep was built to find.")
    nflat = sum(1 for r in inter if r[8])
    if nflat:
        print(f"  {nflat}/{len(inter)} rows are FLAT — no slope setting moves the "
              f"median symbol at that price threshold,\n  so 'best slope' there is "
              f"only the least bad of a tie and must not be read as a preference.")
    sig = [r for r in inter if r[2] > 1e-9 and r[5] < 0.05]
    print(f"  rows whose best beats their own live-slope cell at p<0.05: "
          f"{len(sig)}/{len(inter)}")

    for name, title in (("paired", "paired vs live"), ("sells", "mean sells")):
        g = grids[name]
        # Both axes carry None, so every label goes through str() rather than a
        # numeric format.
        print(f"\n{title}   rows=PERCENT_SELL  cols=SELL_MIN_SIGNAL1")
        print(f"{'':>6} " + " ".join(f"{str(r):>7}" for r in SLOPES))
        for s in SELLS:
            print(f"{str(s):>6} " + " ".join(f"{g.get(_key(s,r), float('nan')):7.2f}"
                                             for r in SLOPES))

    print("\nwhat each metric prefers:")
    for m, (label, unit, d) in METRICS.items():
        gg = grids.get(m) or {}
        if not gg or d == 0:
            continue
        bk, bv = (max if d > 0 else min)(gg.items(), key=lambda kv: kv[1])
        s, r = bk.split("|")
        print(f"  {label:<20} sell={s:<5} slope={r:<6}"
              f" -> {bv:+.2f}{unit}")

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
    print(f"Sweeping {len(SELLS)}x{len(SLOPES)} = {len(SELLS)*len(SLOPES)} cells "
          f"over {len(syms)} symbols")
    print(f"live cell (PERCENT_SELL={LIVE[0]}, SELL_MIN_SIGNAL1={LIVE[1]}) is "
          f"{'in' if _key(*LIVE) in [_key(s, r) for s in SELLS for r in SLOPES] else 'NOT IN'}"
          f" the grid")
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
