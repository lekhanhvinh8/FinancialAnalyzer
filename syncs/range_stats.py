"""Sync (rebuild) the cal_range_close cache for index symbols."""

import database as db
from analyze.range_calc import build_cal_range_close
from ._helpers import _INDEX_SYMBOL_MAP


_DEFAULT_RANGE_DAYS = [1000]
_MAX_WORKERS        = 5


def sync_range_stats(
    symbols: list[str] | None = None,
    index:   str | None = None,
) -> None:
    """
    Rebuild the rolling-range stats cache for one or more index symbols.

    symbols : specific index symbols (e.g. ["VN30"])
    index   : index name ("vn30") — resolved to its index symbol ("VN30")
    None/None → all three main indices

    Always fully rebuilds (DELETE + INSERT). Range stats are always derived
    from DB data, so there is no network fetch.
    """
    targets = _resolve_index_symbols(symbols, index)

    for sym in targets:
        print(f"\n  Rebuilding range_stats for {sym} …")
        _rebuild_one(sym)


def _resolve_index_symbols(symbols, index) -> list[str]:
    if symbols is not None:
        return symbols
    if index is not None:
        return [_INDEX_SYMBOL_MAP.get(index.lower(), index.upper())]
    return list(_INDEX_SYMBOL_MAP.values())[:3]  # VN30, VNDIAMOND, VNFINLEAD


def _rebuild_one(sym: str) -> None:
    prices = db.load_daily_prices(sym).reset_index().rename(columns={"date": "time"})
    pe     = db.load_pe_ratios(sym).reset_index().rename(columns={"date": "time"})

    if prices.empty:
        print(f"  [{sym}] no price data — skipping")
        return

    pe = pe.dropna(subset=["pe_ratio"])[["time", "pe_ratio"]]
    df = prices.merge(pe, on="time", how="left")
    df["pe_ratio"] = df["pe_ratio"].ffill()
    df = df.reset_index(drop=True)

    cal = build_cal_range_close(df, range_days=_DEFAULT_RANGE_DAYS, max_workers=_MAX_WORKERS)
    db.save_range_stats(sym, df, cal)
