"""
How far a quantity strays from zero, as a function of its window — and whether
that follows a clean enough law to normalise a sweep grid by.

WHY THIS EXISTS

  Every threshold in the strategy is compared against a windowed quantity, and
  the spread of that quantity changes with the window. A fixed threshold
  therefore means something different at every window, and a rectangular sweep
  grid spends most of its cells on two degenerate states — "always fires" and
  "never fires" — with a thin diagonal of usable cells between them.

  sweep_sell_signal1 hit this and solved it by sweeping k in

      min_signal1 = k / sqrt(window)

  which came from measuring the slope's spread and finding
  p95 = 3.991 * w^-0.494, R^2 = 0.9994. That measurement was done in a throwaway
  script, so the constant in the docstring cannot be re-checked by anyone. This
  file is that script, kept, and general enough for the next parameter — the same
  question is open for PERCENT_BUY, PERCENT_SELL, PERCENT_REINVEST and
  MIN_SIGNAL3.

USE THE FIT TO PICK A GRID, NEVER AS A THRESHOLD

  The percentiles here are measured over the whole history, so feeding one back
  into the strategy as a threshold would be look-ahead: the backtest would know
  the distribution of its own future. What is safe is arithmetic on the window —
  k/sqrt(w) is a formula, not a fitted quantile. So read the exponent, round it
  to something principled (-0.5, -1, 0), and parameterise with that.

  If no clean law appears (low R^2, or an exponent that is not near anything
  interpretable), that is also an answer: sweep the raw threshold per window and
  accept that the grid's rows are not comparable.

QUANTITIES

  dev    (price - median_w) / median_w * 100, from range_stats. The quantity
         PERCENT_BUY / PERCENT_SELL / PERCENT_REINVEST are compared against.
  slope  signal1_slope from trend_signals — the one already parameterised, kept
         so the 3.991 * w^-0.494 claim can be re-derived.
  sharpe signal3_sharpe from trend_signals, for MIN_SIGNAL3.
  zdev   z_dev from valuation_zdev, for SELL_MIN_ZDEV. Expected to be scale-free
         by construction — it is a z-score — so the interesting question is
         whether that holds at short stat windows, where sigma is estimated from
         few observations and the tails may be fatter than a unit normal's.

RESULTS SO FAR

  Kept here rather than in whichever sweep consumes them, so every figure sits
  next to the command that re-derives it. That is the whole point of the file:
  the slope constant below spent months in a docstring that nobody could check.

  dev    p95 = 1.200 * w^0.712     R2 = 0.9983
         59 symbols, w in 50..1000, 182,522 observations per window
         python analyze/median1000/dispersion.py dev

         Spread GROWS with the window, opposite to slope: p95 runs 19.5 at w=50
         to 156.0 at w=1000. So PERCENT_BUY = 60 is three different strategies —
         above the whole distribution at w=50 (never blocks), the 95th percentile
         at w=250, the 78th at w=1000 (blocks ~22% of days).

         Two limits on the fit, both worth knowing before leaning on it:
         - It normalises SCALE only, and the centre moves too. p50 drifts from
           +0.4 at w=50 to +16.8 at w=1000, because a long median sits far below
           a price that has been rising. Columns are therefore well matched in
           the upper tail, where a buy ceiling actually binds, and drift in the
           lower half — q=0 is about the 49th percentile at w=50 and the 35th at
           w=1000.
         - Worst residual is +8.3 at w=1000 (164 predicted against 156 measured,
           5% high) and -6.7 at w=600. Fine for choosing grid points. Not
           validated below w=50 or above w=1000; measure before extrapolating.

  slope  p95 = 3.991 * w^-0.494    R2 = 0.9994
         45 symbols, w in 10..200, ~3.1M observations
         python analyze/median1000/dispersion.py slope

         Predates this tool, and is what sweep_sell_signal1's k/sqrt(window) rests on.
         Re-derived here on 3 symbols x 5 windows as a = -0.494, R2 = 0.9992 —
         the exponent matches to three decimals, the constant does not (3.604),
         which is what a 3-symbol sample buys you. Re-run in full if the constant
         ever matters; the universe is 59 symbols now, not 45.

  sharpe p95 = 124.600 * w^-0.654   R2 = 0.9971
         python analyze/median1000/dispersion.py sharpe

         Narrows fast, the same direction as slope but steeper. At w=1000 the
         distribution is p5 -0.339, p25 +0.077, p50 +0.423, p75 +0.759,
         p95 +1.360, which is where MIN_SIGNAL3's grid was placed and puts the
         live 1.1 between p75 and p95 — blocking about 11% of sell-eligible days.
         MIN_SIGNAL3 is swept at that one window only, so it needs no
         reparameterisation today; the exponent is the reason a window parameter
         must come with one the day the window is swept.

  zdev   p95 = 2.218 * w^0.009      R2 = 0.27
         w in 50..700
         python analyze/median1000/dispersion.py zdev

         The one scale-free quantity of the four, which is what a z-score should
         be, and worth having confirmed rather than assumed: an exponent of +0.009
         is a flat line, and the R2 is low only because there is no trend left to
         explain. Percentiles hold steady across every window:

             p5     p25     p50     p75     p95
             -2.30  -1.18   -0.15   +1.05   +2.31

         Two departures from a unit normal, both mattering when placing a grid:
         it is WIDER (+-2.3 rather than +-1.64) and its centre sits slightly
         below zero. So SELL_MIN_ZDEV is directly comparable across stat windows
         and sweep_zdev.py sweeps the raw threshold — no k/sqrt(w), no q.

  A NOTE ON "NO LOOK-AHEAD"

  sweep_sell_signal1's docstring calls k/sqrt(w) "arithmetic on the window, not a
  fitted quantile, so it introduces no look-ahead". That is too strong: the 4 in
  4/sqrt(w) is 3.991 rounded, and it was fitted on the full history. The accurate
  claim is narrower — one constant, fixed once, applied identically to every
  symbol and every date, never re-estimated inside the backtest. It shapes which
  cells are worth testing; the winning cell is still a plain fixed pair. Mild,
  standard for grid design, but not none.

Usage:
    python analyze/median1000/dispersion.py dev
    python analyze/median1000/dispersion.py slope
    python analyze/median1000/dispersion.py dev --windows=50,100,250,500,750,1000
    python analyze/median1000/dispersion.py dev --symbols=FPT,STB,HPG
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

import database as db
from analyze.runner import load_symbol_df

DEFAULT_WINDOWS = [50, 100, 150, 250, 400, 600, 800, 1000]
PCTS = [5, 25, 50, 75, 95]

QUANTITIES = {
    # name -> (source table, column, needs the price series)
    "dev":    ("range_stats",   "median",          True),
    "slope":  ("trend_signals", "signal1_slope",   False),
    "sharpe": ("trend_signals", "signal3_sharpe",  False),
    "zdev":   ("valuation_zdev", "z_dev",           False),
}


def _values(sym: str, quantity: str, windows: list) -> dict:
    """
    Returns {window: np.array of observations}. One query per symbol covering
    every window, because range_stats is ~273M rows and a query per window
    turns minutes into an hour.
    """
    table, column, needs_price = QUANTITIES[quantity]
    holder = ",".join("?" * len(windows))
    con = sqlite3.connect("file:stock_data.db?mode=ro", uri=True)
    try:
        if table == "valuation_zdev":
            # min_periods is held equal to stat_window by the writer, so the pair
            # is redundant but both are in the key.
            rows = con.execute(
                f"SELECT stat_window, date, {column} FROM valuation_zdev "
                f"WHERE symbol=? AND median_window=1000 "
                f"AND stat_window IN ({holder}) AND stat_window = min_periods "
                f"AND {column} IS NOT NULL",
                (sym, *windows)).fetchall()
        elif table == "range_stats":
            rows = con.execute(
                f"SELECT range_days, date, {column} FROM range_stats "
                f"WHERE symbol=? AND range_days IN ({holder}) AND {column} IS NOT NULL",
                (sym, *windows)).fetchall()
        else:
            rows = con.execute(
                f"SELECT window_days, date, {column} FROM trend_signals "
                f"WHERE symbol=? AND window_days IN ({holder}) AND {column} IS NOT NULL",
                (sym, *windows)).fetchall()
    finally:
        con.close()
    if not rows:
        return {}

    if needs_price:
        df = load_symbol_df(sym)
        price = {str(pd.Timestamp(t).date()): float(c) * 1000
                 for t, c in zip(df["time"], df["close"])}

    out: dict = {}
    for w, date, v in rows:
        if needs_price:
            p = price.get(date)
            # dev is only defined where both the price and a non-zero median exist
            if p is None or not v:
                continue
            v = (p - v) / v * 100.0
        out.setdefault(w, []).append(v)
    return {w: np.asarray(a, dtype=float) for w, a in out.items()}


def _worker(args):
    sym, quantity, windows = args
    try:
        vals = _values(sym, quantity, windows)
        # Percentiles per symbol would weight a short symbol like a long one; the
        # raw observations are pooled instead, so send back a compact summary
        # plus the data needed to pool exactly.
        return sym, {w: np.sort(a) for w, a in vals.items()}, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {e}"


def _fit_power(windows, values):
    """Least squares on log(value) = log(c) + a*log(w). Returns (c, a, r2)."""
    w = np.asarray([x for x, y in zip(windows, values) if y and y > 0], dtype=float)
    y = np.asarray([y for y in values if y and y > 0], dtype=float)
    if len(w) < 3:
        return None
    lw, ly = np.log(w), np.log(y)
    a, lc = np.polyfit(lw, ly, 1)
    pred = lc + a * lw
    ss_res = float(((ly - pred) ** 2).sum())
    ss_tot = float(((ly - ly.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    return float(np.exp(lc)), float(a), r2


def main():
    args    = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags   = {f.split("=", 1)[0]: f.split("=", 1)[1]
               for f in sys.argv[1:] if f.startswith("--") and "=" in f}
    quantity = (args[0] if args else "dev").lower()
    if quantity not in QUANTITIES:
        print(f"unknown quantity {quantity!r}; choose from {', '.join(QUANTITIES)}")
        return

    windows = ([int(x) for x in flags["--windows"].split(",")]
               if "--windows" in flags else DEFAULT_WINDOWS)
    syms = ([s.strip().upper() for s in flags["--symbols"].split(",")]
            if "--symbols" in flags else db.list_symbols())

    print(f"{quantity}: {len(windows)} windows x {len(syms)} symbols")
    print(f"windows: {windows}\n")
    t0 = time.time()

    pooled: dict = {w: [] for w in windows}
    done = 0
    with ProcessPoolExecutor() as ex:
        futs = {ex.submit(_worker, (s, quantity, windows)): s for s in syms}
        for fut in as_completed(futs):
            sym, vals, err = fut.result()
            done += 1
            if err:
                print(f"[{done}/{len(syms)}] {sym} — {err}", flush=True)
                continue
            for w, a in vals.items():
                pooled[w].append(a)
            print(f"[{done}/{len(syms)}] {sym} "
                  f"({sum(len(a) for a in vals.values()):,} obs)", flush=True)

    rows = {}
    for w in windows:
        if not pooled[w]:
            continue
        a = np.concatenate(pooled[w])
        rows[w] = {"n": len(a),
                   **{f"p{p}": float(np.percentile(a, p)) for p in PCTS},
                   "spread": float(np.percentile(a, 95) - np.percentile(a, 5))}

    if not rows:
        print("\nno observations — check the quantity and the windows")
        return

    ws = sorted(rows)
    print(f"\n{'window':>7} {'obs':>12} " + " ".join(f"{'p'+str(p):>9}" for p in PCTS)
          + f" {'p95-p5':>9}")
    for w in ws:
        r = rows[w]
        print(f"{w:>7} {r['n']:>12,} "
              + " ".join(f"{r['p'+str(p)]:9.3f}" for p in PCTS)
              + f" {r['spread']:9.3f}")

    print("\npower-law fit   value = c * w^a")
    for name in ("p95", "spread"):
        fit = _fit_power(ws, [rows[w][name] for w in ws])
        if fit is None:
            print(f"  {name:<7} not enough positive points to fit")
            continue
        c, a, r2 = fit
        near = min([(-1.0, "1/w"), (-0.5, "1/sqrt(w)"), (0.0, "constant"),
                    (0.5, "sqrt(w)"), (1.0, "w")], key=lambda t: abs(t[0] - a))
        note = f"~ {near[1]}" if abs(near[0] - a) < 0.12 else "no round exponent nearby"
        print(f"  {name:<7} c={c:8.3f}  a={a:+.3f}  R2={r2:.4f}   {note}")

    print(f"\nRead the exponent, not the constant: round it to something "
          f"principled and\nparameterise with that. A fitted quantile used as a "
          f"threshold is look-ahead.")
    print(f"({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
