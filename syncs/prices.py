"""Sync daily price series for stocks and indices."""

import time
from datetime import date as _date

import pandas as pd
import database as db
from sources import vnstock
from ._helpers import PRICE_START, call_with_retry, resolve_symbols

_PRICE_COLS = ["close"]


def sync_prices(
    symbols: list[str] | None = None,
    index:   str | None = None,
    start:   str | None = None,
    override: bool = False,
) -> None:
    """
    Sync daily close prices.

    symbols  : specific symbols to sync
    index    : index name ("vn30", "vndiamond", "vnfinlead") →
               syncs the index price series itself (not its member stocks)
    start    : fetch from this date; None = from PRICE_START (2012-01-01)
    override : False → insert new rows; fill NULL columns in existing rows
               True  → overwrite all columns in all rows
    """
    today      = _date.today().isoformat()
    fetch_from = start or PRICE_START
    resolved   = resolve_symbols(symbols, index)

    for sym, sym_type in resolved:
        try:
            _sync_one(sym, sym_type, fetch_from, today, override)
        except Exception as e:
            print(f"  ERROR [prices] {sym}: {e}")
        time.sleep(5)


def _sync_one(sym: str, sym_type: str, fetch_from: str, today: str, override: bool) -> None:
    getter = vnstock.get_index_prices if sym_type == "index" else vnstock.get_prices
    df = call_with_retry(getter, sym, fetch_from, today, label=sym)

    if df is None or df.empty:
        print(f"  [prices] {sym}: no data returned")
        return

    if not override:
        df = _fill_merge(df, db.load_daily_prices(sym))

    if df.empty:
        print(f"  [prices] {sym}: up to date")
        return

    db.save_daily_prices(sym, df, symbol_type=sym_type)


def _fill_merge(new_df: pd.DataFrame, existing: pd.DataFrame) -> pd.DataFrame:
    """
    For override=False: return only rows/columns that need writing.
    - New dates (not in existing)      → keep as-is
    - Existing dates with NULL columns → keep only the null-filling values
    - Existing dates with no NULLs     → drop (nothing to update)
    """
    if existing.empty:
        return new_df

    result = []
    for date, new_row in new_df.iterrows():
        date_str = date.strftime("%Y-%m-%d")
        if date_str not in existing.index.strftime("%Y-%m-%d"):
            result.append(new_row)
            continue

        ex_row = existing.loc[existing.index.strftime("%Y-%m-%d") == date_str].iloc[0]
        merged = new_row.copy()
        has_null = False
        for col in _PRICE_COLS:
            if col in ex_row and pd.notna(ex_row[col]):
                merged[col] = ex_row[col]  # preserve existing non-null
            else:
                has_null = True            # DB has null — this row needs writing

        if has_null:
            result.append(merged)

    return pd.DataFrame(result, columns=new_df.columns) if result else pd.DataFrame()
