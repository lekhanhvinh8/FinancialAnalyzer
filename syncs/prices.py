"""Sync daily price series for stocks and indices."""

import time
from datetime import date as _date

import database as db
from sources import vnstock
from ._helpers import PRICE_START, call_with_retry, resolve_symbols, fill_merge, is_price_current

_PRICE_COLS = ["close"]

# A bonus issue, split or stock dividend makes the source rescale its whole
# history retroactively. Anything past this much disagreement on a date we
# already stored is that rescale, not noise: the tick size is 100 VND and the
# source does not otherwise revise a settled close. Set low enough to also
# catch a cash-dividend adjustment, which is usually 1-3%.
_ADJ_TOLERANCE = 0.01

# How many of the oldest shared dates to judge on. The oldest rows are always
# on the far side of an ex-date, so they carry the full factor no matter how
# long the break went unnoticed. An incremental sync usually shares exactly one
# date with the DB, which is enough — the extra rows only steady the median
# when a full-range sync gives us more to work with.
_ADJ_SAMPLE = 60


def sync_prices(
    symbols: list[str] | None = None,
    index:   str | None = None,
    start:   str | None = None,
    override: bool = False,
) -> list[str]:
    """
    Sync daily close prices.

    symbols  : specific symbols to sync
    index    : index name ("vn30", "vndiamond", "vnfinlead") →
               syncs the index price series itself (not its member stocks)
    start    : fetch from this date; None = from PRICE_START (2012-01-01)
    override : False → insert new rows; fill NULL columns in existing rows
               True  → overwrite all columns in all rows

    Returns the symbols whose full series was rewritten because the source had
    re-adjusted it. Their pe_ratios, range_stats, trend_signals and zdev caches
    are stale — every one of those is keyed to a price level — so the caller
    must rebuild them rather than resume from its last stored date.
    """
    today      = _date.today().isoformat()
    fetch_from = start or PRICE_START
    resolved   = resolve_symbols(symbols, index)
    readjusted = []

    for sym, sym_type in resolved:
        if not override and is_price_current(sym):
            print(f"  [prices] {sym}: up to date")
            continue
        try:
            saved, rewritten = _sync_one(sym, sym_type, fetch_from, today, override)
            if rewritten:
                readjusted.append(sym)
        except Exception as e:
            print(f"  ERROR [prices] {sym}: {e}")
            saved = True  # unknown state — keep the sleep
        if saved:
            time.sleep(5)

    return readjusted


def detect_adjustment(new_df, existing) -> float | None:
    """
    Compare a freshly fetched series against what we stored for the same dates.

    The source back-adjusts its whole history on a corporate action; our rows
    do not move, so from the ex-date backwards the two disagree by a constant
    factor. Returns that factor (stored / source), or None when they line up.
    """
    if existing is None or existing.empty or new_df is None or new_df.empty:
        return None

    joined = existing.join(new_df, how="inner", lsuffix="_db", rsuffix="_api").sort_index()
    joined = joined.dropna(subset=["close_db", "close_api"])
    joined = joined[joined["close_api"] > 0]
    if joined.empty:
        return None

    ratio  = joined["close_db"].head(_ADJ_SAMPLE) / joined["close_api"].head(_ADJ_SAMPLE)
    factor = float(ratio.median())
    return factor if abs(factor - 1.0) > _ADJ_TOLERANCE else None


def _sync_one(
    sym: str, sym_type: str, fetch_from: str, today: str, override: bool
) -> tuple[bool, bool]:
    """
    Returns (api_called, rewritten):
      api_called — an API call was made, so the caller should sleep
      rewritten  — the full series was replaced after an adjustment was found
    """
    getter = vnstock.get_index_prices if sym_type == "index" else vnstock.get_prices
    df = call_with_retry(getter, sym, fetch_from, today, label=sym)

    if df is None or df.empty:
        print(f"  [prices] {sym}: no data returned")
        return True, False

    existing  = db.load_daily_prices(sym)
    rewritten = False

    if not override:
        factor = detect_adjustment(df, existing)
        if factor is not None:
            print(f"  [prices] {sym}: source re-adjusted its history — stored closes are "
                  f"{factor:.4g}x the source. Refetching the full series.")
            if fetch_from > PRICE_START:
                # The incremental window is only the last few days; the stale
                # scale runs the whole way back, so nothing short of a full
                # refetch repairs it.
                time.sleep(5)
                df = call_with_retry(getter, sym, PRICE_START, today, label=sym)
                if df is None or df.empty:
                    print(f"  [prices] {sym}: full refetch returned nothing — leaving the series alone")
                    return True, False
            override  = True
            rewritten = True

    if not override:
        df = df.reset_index()
        df = df.rename(columns={df.columns[0]: "date_key"})
        existing = existing.reset_index()
        existing = existing.rename(columns={existing.columns[0]: "date_key"})
        existing["date_key"] = existing["date_key"].dt.strftime("%Y-%m-%d")
        df["date_key"] = df["date_key"].dt.strftime("%Y-%m-%d")
        df = fill_merge(df, existing, cols=_PRICE_COLS, key_cols=["date_key"])
        if df.empty:
            print(f"  [prices] {sym}: up to date")
            return False, False
        df = df.set_index("date_key")
        df.index = _date_index(df.index)

    if df.empty:
        print(f"  [prices] {sym}: up to date")
        return False, False

    db.save_daily_prices(sym, df, symbol_type=sym_type)
    return True, rewritten


def _date_index(str_index):
    import pandas as pd
    return pd.to_datetime(str_index)
