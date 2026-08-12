"""
How far a quantity strays from zero, as a function of its window — and whether
that follows a clean enough law to normalise a sweep grid by.

WHY THIS EXISTS

  Every threshold in the strategy is compared against a windowed quantity, and
  the spread of that quantity changes with the window. A fixed threshold
  therefore means something different at every window, and a rectangular sweep
  grid spends most of its cells on two degenerate states — "always fires" and
  "never fires" — with a thin diagonal of usable cells between them.

  sweep_signal1 hit this and solved it by sweeping k in

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
        if table == "range_stats":
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
