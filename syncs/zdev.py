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

INCREMENTAL, AND WHY IT IS SAFE

  This used to recompute and rewrite every row on every sync — ~2M rows per
  symbol, ~110M in total, whether or not anything had changed. It also defaulted
  to override=True, the only sync in the package that did; the other six default
  to False.

  The reason given for the full rebuild was real: prices are re-fetched from 2012
  and INSERT OR REPLACE'd on every run, so a corporate action can rewrite years
  of history behind our back, and everything derived from it would then be stale.
  Recomputing everything daily is a very expensive way to insure against an event
  that happens a few times a year per symbol.

  So the input is fingerprinted instead. A hash of the close series is stored
  beside the output; on the next sync it is recomputed and compared:

      same hash  -> history is untouched, only write dates past what is stored
      differs    -> history was revised, rebuild this symbol in full
      override=True -> rebuild regardless, which is what a code change needs
                       since the hash tracks inputs and not this file

  A hash match plus a stored date equal to the last price means a window is
  already current and is skipped entirely — no rolling computation, no write.

  What is NOT skipped is the warmup: a value still needs median_window +
  stat_window bars behind it, so dev and the rolling stats are computed over the
  full series and only the tail is written. That costs milliseconds and removes
  any chance of a boundary bug.
"""

import hashlib
from itertools import repeat

import numpy as np
import pandas as pd

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


def price_fingerprint(closes: "pd.Series") -> str:
    """
    Hash of the full close series. Cheap — a few thousand floats — and it changes
    if any historical value is revised, not only if new dates arrive.
    """
    h = hashlib.blake2b(digest_size=16)
    for d, v in closes.items():
        h.update(f"{d}:{v!r}|".encode())
    return h.hexdigest()


def adopt_existing(symbols: list[str] | None = None, index: str | None = None,
                   median_window: int = MEDIAN_WINDOW) -> None:
    """
    Record the fingerprint for symbols whose z_dev is already complete, so the
    switch to incremental costs nothing.

    Without this, every symbol needs one full rebuild purely to establish a
    fingerprint — ~2 minutes each, ~2 hours over the universe — to produce rows
    that already exist and are already correct: the old full-rebuild sync built
    them from the same prices this fingerprint is taken from.

    A symbol is adopted only when its newest stored z_dev date equals its newest
    price. Anything short of that is left alone and rebuilt normally, so a
    partially built symbol is never adopted.
    """
    adopted = skipped = 0
    for sym, _ in resolve_symbols(symbols, index):
        prices = db.load_daily_prices(sym)
        if prices.empty or len(prices) < median_window:
            continue
        last_price = str(prices.index[-1].date())
        latest = db.load_zdev_latest_by_window(sym, median_window)
        if latest and max(latest.values()) >= last_price:
            db.save_sync_fingerprint("zdev", sym, str(median_window),
                                     price_fingerprint(prices["close"]))
            adopted += 1
        else:
            skipped += 1
    print(f"  [zdev] adopted {adopted} symbols as current, "
          f"{skipped} left for a normal rebuild")


def sync_zdev(
    symbols:       list[str] | None = None,
    index:         str | None       = None,
    median_window: int              = MEDIAN_WINDOW,
    stat_start:    int              = STAT_START,
    stat_end:      int              = STAT_END,
    stat_step:     int              = STAT_STEP,
    override:      bool             = False,
) -> None:
    """
    Sync dev and the swept z_dev configurations for one or more symbols.

    symbols  : specific symbols; None = all in DB
    index    : index name ("vn30") — resolved to its index symbol
    override : force a full rebuild. Default False, matching every other sync in
               the package. Leave it off for routine syncs — the fingerprint
               already forces a rebuild when the price history changes. Turn it
               on when THIS FILE changes, since the fingerprint tracks inputs and
               cannot see a new formula.
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

    # Has the input changed, or only grown?
    variant = str(median_window)
    fp      = price_fingerprint(prices["close"])
    stored  = db.load_sync_fingerprint("zdev", sym, variant)
    full    = override or stored != fp

    latest = {} if full else db.load_zdev_latest_by_window(sym, median_window)
    last_price_date = str(prices.index[-1].date())

    # dev once — it does not depend on the stat window
    dev = compute_dev(prices["close"], median_window)
    dev_valid = dev[dev.notna()]
    if dev_valid.empty:
        print(f"  [zdev] {sym}: no rows past the median warmup — skipping")
        return

    # override=full, not override: a fingerprint mismatch means the old dev
    # values are wrong and must be replaced, even though the caller did not ask
    # for a forced rebuild. On the incremental path the new dates do not exist
    # yet, so IGNORE and REPLACE do the same thing.
    db.save_dev(
        sym,
        [(sym, str(d.date()), median_window, float(v)) for d, v in dev_valid.items()],
        override=full,
    )

    # then each stat window, storing only rows that actually carry a z_dev.
    # Buffered and flushed in chunks — see WRITE_CHUNK.
    buf: list[tuple] = []
    total = cfgs = 0

    def flush():
        nonlocal buf, total
        if buf:
            total += db.save_zdev(sym, buf, override=full)["saved"]
            buf = []

    # Date strings are the same for every window — build them once rather than
    # re-formatting ~3M datetimes per symbol.
    all_dates = [str(d.date()) for d in dev.index]

    skipped = 0
    for sw in windows:
        if sw > len(dev_valid):
            break  # no chance of a full window from here on

        # Already current: nothing to compute and nothing to write.
        cutoff = latest.get(sw)
        if cutoff is not None and cutoff >= last_price_date:
            skipped += 1
            continue

        # Computed over the FULL series even when only the tail is written — a
        # value needs median_window + stat_window bars behind it, and slicing the
        # input to save milliseconds is how a warmup boundary bug gets in.
        mu, sigma, z = zdev_arrays(dev, sw, sw)
        idx = np.flatnonzero(~np.isnan(z))
        if cutoff is not None:
            idx = idx[[all_dates[i] > cutoff for i in idx]]
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

    # Written last: if anything above raised, the fingerprint stays stale and the
    # next run rebuilds rather than trusting a half-written symbol.
    db.save_sync_fingerprint("zdev", sym, variant, fp)

    if cfgs or skipped:
        mode = "full" if full else "incremental"
        print(f"  [zdev] {sym}: {mode} | dev {len(dev_valid)} rows | "
              f"z_dev {total} rows across {cfgs} stat windows"
              + (f", {skipped} already current" if skipped else ""))
    else:
        need = median_window + windows[0]
        print(f"  [zdev] {sym}: dev {len(dev_valid)} rows | no z_dev yet "
              f"({n} bars, smallest config needs {need})")
