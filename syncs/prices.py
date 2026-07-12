"""Sync daily price series for stocks and indices."""

import time
from datetime import date as _date

import database as db
from sources import vnstock
from ._helpers import PRICE_START, call_with_retry, resolve_symbols, fill_merge

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
        df = df.reset_index().rename(columns={"date": "date_key"})
        existing = db.load_daily_prices(sym).reset_index().rename(columns={"date": "date_key"})
        existing["date_key"] = existing["date_key"].dt.strftime("%Y-%m-%d")
        df["date_key"] = df["date_key"].dt.strftime("%Y-%m-%d")
        df = fill_merge(df, existing, cols=_PRICE_COLS, key_cols=["date_key"])
        if df.empty:
            print(f"  [prices] {sym}: up to date")
            return
        df = df.set_index("date_key")
        df.index = _date_index(df.index)

    if df.empty:
        print(f"  [prices] {sym}: up to date")
        return

    db.save_daily_prices(sym, df, symbol_type=sym_type)


def _date_index(str_index):
    import pandas as pd
    return pd.to_datetime(str_index)
