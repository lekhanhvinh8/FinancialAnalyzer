"""Sync (rebuild) the cal_range_close cache for index symbols."""

import database as db
from analyze.range_calc import build_cal_range_close
from ._helpers import resolve_symbols, is_range_stats_current


_DEFAULT_RANGE_DAYS = list(range(50, 1001, 50))  # [50, 100, ..., 1000]
_DEFAULT_MAX_WORKERS = 5


def sync_range_stats(
    symbols:     list[str] | None = None,
    index:       str | None = None,
    start:       str | None = None,
    override:    bool = False,
    max_workers: int | None = None,
) -> None:
    """
    Rebuild the rolling-range stats cache for one or more symbols.

    symbols     : specific symbols
    index       : index name ("vn30") — resolved to its index symbol ("VN30")
    None/None   → all symbols in DB
    start       : only write rows for dates >= start; None = all dates
    override    : True  → replace existing rows (INSERT OR REPLACE)
                  False → only insert new rows (INSERT OR IGNORE)
    max_workers : parallel worker processes (default: 5)
    """
    workers = max_workers if max_workers is not None else _DEFAULT_MAX_WORKERS
    targets = resolve_symbols(symbols, index)

    for sym, _ in targets:
        if not override and is_range_stats_current(sym):
            print(f"  [range_stats] {sym}: up to date")
            continue
        print(f"\n  Rebuilding range_stats for {sym} …")
        _rebuild_one(sym, start, override, workers)


def _rebuild_one(sym: str, start: str | None, override: bool, max_workers: int) -> None:
    prices = db.load_daily_prices(sym).reset_index().rename(columns={"date": "time"})
    pe     = db.load_pe_ratios(sym).reset_index().rename(columns={"date": "time"})

    if prices.empty:
        print(f"  [{sym}] no price data — skipping")
        return

    pe = pe.dropna(subset=["pe_ratio"])[["time", "pe_ratio"]]
    df = prices.merge(pe, on="time", how="left")
    df["pe_ratio"] = df["pe_ratio"].ffill()
    df = df.reset_index(drop=True)

    # determine start_idx: only compute rows we need to save
    if override:
        start_idx = 0
    else:
        # use explicit start param, or fall back to last saved date in DB
        cutoff = start or db.load_latest_range_stats_date(sym)
        if cutoff is not None:
            mask = df["time"].astype(str) > cutoff
            start_idx = int(df[mask].index[0]) if mask.any() else len(df)
        else:
            start_idx = 0

    if start_idx >= len(df):
        print(f"  [range_stats] {sym}: up to date")
        return

    total_saved = 0

    def _save_batch(batch: dict) -> None:
        nonlocal total_saved
        result = db.save_range_stats(sym, df, batch, override=override, quiet=True)
        total_saved += result["saved"]

    build_cal_range_close(
        df,
        range_days=_DEFAULT_RANGE_DAYS,
        max_workers=max_workers,
        batch_callback=_save_batch,
        start_idx=start_idx,
    )

    if total_saved == 0:
        print(f"  [range_stats] {sym}: up to date")
    else:
        print(f"  [range_stats] {sym}: saved {total_saved} rows")
