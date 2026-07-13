"""Sync (rebuild) the cal_range_close cache for index symbols."""

import database as db
from analyze.range_calc import build_cal_range_close
from ._helpers import resolve_symbols


_DEFAULT_RANGE_DAYS = list(range(50, 1001, 50))  # [50, 100, ..., 1000]
_MAX_WORKERS        = 5


def sync_range_stats(
    symbols:  list[str] | None = None,
    index:    str | None = None,
    start:    str | None = None,
    override: bool = False,
) -> None:
    """
    Rebuild the rolling-range stats cache for one or more symbols.

    symbols  : specific symbols
    index    : index name ("vn30") — resolved to its index symbol ("VN30")
    None/None → all symbols in DB
    start    : only write rows for dates >= start; None = all dates
               Note: full history is always used to compute stats regardless
    override : True  → replace existing rows (INSERT OR REPLACE)
               False → only insert new rows (INSERT OR IGNORE)
    """
    targets = resolve_symbols(symbols, index)

    for sym, _ in targets:
        print(f"\n  Rebuilding range_stats for {sym} …")
        _rebuild_one(sym, start, override)


def _rebuild_one(sym: str, start: str | None, override: bool) -> None:
    prices = db.load_daily_prices(sym).reset_index().rename(columns={"date": "time"})
    pe     = db.load_pe_ratios(sym).reset_index().rename(columns={"date": "time"})

    if prices.empty:
        print(f"  [{sym}] no price data — skipping")
        return

    pe = pe.dropna(subset=["pe_ratio"])[["time", "pe_ratio"]]
    df = prices.merge(pe, on="time", how="left")
    df["pe_ratio"] = df["pe_ratio"].ffill()
    df = df.reset_index(drop=True)

    # precompute valid indices for start filter (full df needed for accurate stats)
    valid_idxs = None
    if start is not None:
        mask       = df["time"].astype(str) >= start
        valid_idxs = set(df[mask].index)

    total_saved = 0

    def _save_batch(batch: dict) -> None:
        nonlocal total_saved
        if valid_idxs is not None:
            batch = {k: v for k, v in batch.items() if k in valid_idxs}
        if batch:
            result = db.save_range_stats(sym, df, batch, override=override, quiet=True)
            total_saved += result["saved"]

    build_cal_range_close(
        df,
        range_days=_DEFAULT_RANGE_DAYS,
        max_workers=_MAX_WORKERS,
        batch_callback=_save_batch,
    )

    if total_saved == 0:
        print(f"  [range_stats] {sym}: up to date")
    else:
        print(f"  [range_stats] {sym}: saved {total_saved} rows")
