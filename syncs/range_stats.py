"""Sync (rebuild) the cal_range_close cache for index symbols."""

import database as db
from analyze.range_calc import build_cal_range_close
from ._helpers import resolve_symbols


_DEFAULT_RANGE_DAYS = [1000]
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

    # compute using full history (needed for accurate stats)
    cal = build_cal_range_close(df, range_days=_DEFAULT_RANGE_DAYS, max_workers=_MAX_WORKERS)

    # filter to start date — use original indices to match cal keys correctly
    if start is not None:
        mask        = df["time"].astype(str) >= start
        valid_idxs  = set(df[mask].index)
        cal         = {k: v for k, v in cal.items() if k in valid_idxs}
        df          = df[mask]

    db.save_range_stats(sym, df, cal, override=override)
