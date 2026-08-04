"""
Sync relative-valuation z_dev into valuation_dev + valuation_zdev.

  dev   = ln(price / rolling median)          -> valuation_dev
  mu    = rolling mean of dev, shifted 1 bar  -> valuation_zdev
  sigma = rolling std  of dev, shifted 1 bar  -> valuation_zdev
  z_dev = (dev - mu) / sigma                  -> valuation_zdev

See analyze/zdev_calc.py for the reasoning behind each term.

Two tables, because dev depends only on median_window. Storing it inside the
swept table would repeat the same 123k values once per stat window.

THE SWEEP
  median_window is fixed (1000 — ~4 years, matching range_stats and the
  Median1000 strategies).

  stat_window is swept, and min_periods is held equal to it. They move together
  on purpose: pandas requires min_periods <= window, so min_periods alone cannot
  exceed stat_window; and holding them equal means every value in a given
  configuration is built from the same number of samples, which is what makes
  z_dev comparable across symbols. A configuration's first z_dev lands at
  bar median_window + stat_window.

  Sweeping stat_window with min_periods pinned lower would instead produce
  configurations that are identical to each other after the warmup and differ
  only in a thin early stretch — far more storage for far less information.

  Defaults sweep every window 1..1500 (1500 configurations, ~124M rows). Note
  stat_window=1 yields no z_dev at all: a standard deviation with ddof=1 needs
  at least two observations.

No incremental mode. A value still needs median_window + stat_window bars of
history behind it, so an incremental update saves almost nothing while adding a
warmup-boundary bug to get wrong. Each symbol is recomputed in full.
"""

from itertools import repeat

import numpy as np

import database as db
from analyze.zdev_calc import compute_dev, zdev_arrays, MEDIAN_WINDOW
from ._helpers import resolve_symbols

STAT_START = 1
STAT_END   = 1500
STAT_STEP  = 1

# Rows are buffered across stat windows and flushed in chunks. One write per
# window costs ~1500 transactions per symbol; one write per symbol would hold
# ~3M tuples (~0.6 GB) in memory for the longest series. This is the middle.
WRITE_CHUNK = 500_000


def stat_windows(start: int = STAT_START, end: int = STAT_END, step: int = STAT_STEP) -> list[int]:
    return list(range(start, end + 1, step))


def sync_zdev(
    symbols:       list[str] | None = None,
    index:         str | None       = None,
    median_window: int              = MEDIAN_WINDOW,
    stat_start:    int              = STAT_START,
    stat_end:      int              = STAT_END,
    stat_step:     int              = STAT_STEP,
    override:      bool             = True,
) -> None:
    """
    Rebuild dev and the swept z_dev configurations for one or more symbols.

    symbols  : specific symbols; None = all in DB
    index    : index name ("vn30") — resolved to its index symbol
    override : True → INSERT OR REPLACE (default; the metric is derived)
    """
    windows = stat_windows(stat_start, stat_end, stat_step)
    for sym, _ in resolve_symbols(symbols, index):
        _rebuild_one(sym, median_window, windows, override)


def _rebuild_one(sym: str, median_window: int, windows: list[int], override: bool) -> None:
    prices = db.load_daily_prices(sym)
    if prices.empty:
        print(f"  [zdev] {sym}: no price data — skipping")
        return

    n = len(prices)
    if n < median_window:
        print(f"  [zdev] {sym}: {n} rows < median_window {median_window} — skipping")
        return

    # dev once — it does not depend on the stat window
    dev = compute_dev(prices["close"], median_window)
    dev_valid = dev[dev.notna()]
    if dev_valid.empty:
        print(f"  [zdev] {sym}: no rows past the median warmup — skipping")
        return

    db.save_dev(
        sym,
        [(sym, str(d.date()), median_window, float(v)) for d, v in dev_valid.items()],
        override=override,
    )

    # then each stat window, storing only rows that actually carry a z_dev.
    # Buffered and flushed in chunks — see WRITE_CHUNK.
    buf: list[tuple] = []
    total = cfgs = 0

    def flush():
        nonlocal buf, total
        if buf:
            total += db.save_zdev(sym, buf, override=override)["saved"]
            buf = []

    # Date strings are the same for every window — build them once rather than
    # re-formatting ~3M datetimes per symbol.
    all_dates = [str(d.date()) for d in dev.index]

    for sw in windows:
        if sw > len(dev_valid):
            break  # no chance of a full window from here on
        mu, sigma, z = zdev_arrays(dev, sw, sw)
        idx = np.flatnonzero(~np.isnan(z))
        if idx.size == 0:
            continue
        # z non-null implies mu/sigma non-null, so no NaN handling is needed here.
        # .tolist() yields Python floats — sqlite3 cannot bind numpy scalars.
        buf.extend(zip(
            repeat(sym), (all_dates[i] for i in idx),
            repeat(median_window), repeat(sw), repeat(sw),
            mu[idx].tolist(), sigma[idx].tolist(), z[idx].tolist(),
        ))
        cfgs += 1
        if len(buf) >= WRITE_CHUNK:
            flush()
    flush()

    if cfgs:
        print(f"  [zdev] {sym}: dev {len(dev_valid)} rows | "
              f"z_dev {total} rows across {cfgs}/{len(windows)} stat windows")
    else:
        need = median_window + windows[0]
        print(f"  [zdev] {sym}: dev {len(dev_valid)} rows | no z_dev yet "
              f"({n} bars, smallest config needs {need})")
