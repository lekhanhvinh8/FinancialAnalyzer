"""Sync quarterly outstanding shares (stocks only, via vnstock)."""

import time

import database as db
from sources import vnstock
from ._helpers import call_with_retry, resolve_stocks, fill_merge, is_shares_current

_SHARES_COLS = ["shares"]


def sync_shares(
    symbols:      list[str] | None = None,
    index:        str | None = None,
    from_year:    int | None = None,
    from_quarter: int | None = None,
    override:     bool = False,
) -> None:
    """
    Sync quarterly outstanding shares for stocks.

    symbols/index: which stocks to sync (index= resolves to its current members)
    from_year/from_quarter: only process quarters >= this point; None = all
    override: False → insert new rows; fill NULL shares in existing rows
              True  → overwrite all shares values
    """
    stocks = resolve_stocks(symbols, index)

    for sym in stocks:
        if not override and is_shares_current(sym):
            print(f"  [shares] {sym}: up to date")
            continue
        try:
            _sync_one(sym, from_year, from_quarter, override)
        except Exception as e:
            print(f"  ERROR [shares] {sym}: {e}")
        time.sleep(5)


def _sync_one(sym: str, from_year, from_quarter, override: bool) -> None:
    df = call_with_retry(vnstock.get_shares, sym, label=sym)

    if df is None or df.empty:
        print(f"  [shares] {sym}: no data returned")
        return

    if from_year is not None:
        fq = from_quarter or 1
        df = df[
            (df["year"] > from_year) |
            ((df["year"] == from_year) & (df["quarter"] >= fq))
        ]

    if df.empty:
        print(f"  [shares] {sym}: nothing to update for given range")
        return

    if not override:
        df = fill_merge(df, db.load_shares(sym), cols=_SHARES_COLS, key_cols=["year", "quarter"])

    if df.empty:
        print(f"  [shares] {sym}: up to date")
        return

    db.save_shares(sym, df)
