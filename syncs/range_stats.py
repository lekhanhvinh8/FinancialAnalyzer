"""Sync (rebuild) the cal_range_close cache for index symbols."""

import database as db
from analyze.range_calc import build_cal_range_close
from ._helpers import _INDEX_SYMBOL_MAP


_DEFAULT_RANGE_DAYS = [1000]
_MAX_WORKERS        = 5


def sync_range_stats(
    symbols:  list[str] | None = None,
    index:    str | None = None,
    override: bool = True,
) -> None:
    """
    Rebuild the rolling-range stats cache for one or more index symbols.

    symbols  : specific symbols
    index    : index name ("vn30") — resolved to its index symbol ("VN30")
    None/None → all index symbols in DB
    override : True  → delete existing rows then reinsert (full rebuild)
               False → insert only rows not already in DB (INSERT OR IGNORE)

    No network fetch — purely derived from DB prices + PE data.
    No start parameter — range stats require full history to compute.
    """
    targets = _resolve_symbols(symbols, index)

    for sym in targets:
        print(f"\n  Rebuilding range_stats for {sym} …")
        _rebuild_one(sym, override)


def _resolve_symbols(symbols, index) -> list[str]:
    if symbols is not None:
        return symbols
    if index is not None:
        return [_INDEX_SYMBOL_MAP.get(index.lower(), index.upper())]
    return db.list_symbols(symbol_type="index")


def _rebuild_one(sym: str, override: bool) -> None:
    prices = db.load_daily_prices(sym).reset_index().rename(columns={"date": "time"})
    pe     = db.load_pe_ratios(sym).reset_index().rename(columns={"date": "time"})

    if prices.empty:
        print(f"  [{sym}] no price data — skipping")
        return

    pe = pe.dropna(subset=["pe_ratio"])[["time", "pe_ratio"]]
    df = prices.merge(pe, on="time", how="left")
    df["pe_ratio"] = df["pe_ratio"].ffill()
    df = df.reset_index(drop=True)

    if override:
        db.delete_range_stats(sym)

    cal = build_cal_range_close(df, range_days=_DEFAULT_RANGE_DAYS, max_workers=_MAX_WORKERS)
    db.save_range_stats(sym, df, cal)
